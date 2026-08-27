"""The weekly run — steps 1 through 6 in order.

Each step is in its own module and names the read path it serves; this file is
only the sequence. docs/pipeline.md is the prose version of exactly this.
"""

from __future__ import annotations

import os

from .. import db, geography
from ..config import Config
from ..crm import fieldmap as fieldmap_mod
from ..crm.fieldmap import FieldMap
from ..crm.hubspot import HubSpot
from ..crm.salesforce import Salesforce
from . import coverage as coverage_mod
from . import people as people_mod
from . import stakeholders as stakeholders_mod
from . import view as view_mod
from . import workbook as workbook_mod


class MissingFocusProfile(RuntimeError):
    """No active focus profile for the account.

    Fatal rather than a warning, because the failure is invisible in the
    output: `meets_profile` treats an absent profile as "everything fits", so
    the run completes, the workbook has the usual shape, and every company met
    that week is reported as an ICP target. A reader cannot tell that from a
    correct run. `quorom init` creates one.
    """


class MissingFieldMap(RuntimeError):
    """Salesforce is configured but no field map has been resolved for it.

    Fatal for the same reason: the map is where the non-standard field names
    come from, so a run without one reads standard fields only — no headcount
    from a package field, no HQ, no LinkedIn — and the ICP test then judges
    every company on data it did not fetch. `quorom resolve-fields` writes one.
    """


def run_weekly(cfg: Config, log=print) -> dict:
    start, end = cfg.week_bounds()
    log(f"[*] Week window: {start} .. {end}  account={cfg.account}")

    sf = Salesforce(cfg)
    hs = HubSpot(cfg)
    if not sf.configured:
        log("[i] Salesforce not configured — 'In Salesforce?' will read 'not checked'.")
    elif sf._cfg.uses_client_credentials:
        log("[i] Salesforce: client-credentials flow.")
    else:
        log("[i] Salesforce: pasted token (expires ~2h — see docs/salesforce-access.md).")
    if not hs.configured:
        log("[i] HubSpot not configured — 'In HubSpot?' will read 'not checked'.")

    with db.connect(cfg) as conn:
        # Read first, before any work: the profile carries the ICP test and the
        # seniority bar, so a run without one is wrong from step 4 onwards.
        # Failing here costs a second; failing where it is used costs every
        # Salesforce and HubSpot call made in between.
        profile = db.focus_profile(conn, cfg)
        if not profile:
            raise MissingFocusProfile(
                f"No active focus profile for account {cfg.account!r}. It carries "
                "the ICP test (employee band, HQ geography) and the seniority bar, "
                "and without one every company met would be reported as an ICP "
                "target — an artifact that looks normal and is wrong. "
                "Create one with `quorom init`."
            )
        # Validated here, before any work, rather than per company inside the
        # ICP test: a geography the test cannot act on is a broken profile, and
        # it used to mean no geography filter was applied at all.
        selections = geography.parse_selections(profile.get("hq_geographies"))
        log(
            f"[*] Focus profile: emp {profile.get('employee_count_min')}-"
            f"{profile.get('employee_count_max')}, geo {geography.label(selections)}, "
            f"seniority {profile.get('focus_seniority')}"
        )

        # The resolved CRM field map, for the same reason and at the same point:
        # it decides which fields every Salesforce query below asks for.
        field_map = db.crm_field_map(conn, cfg)
        if sf.configured and not field_map:
            raise MissingFieldMap(
                f"Salesforce is configured but account {cfg.account!r} has no "
                "resolved CRM field map. Every query would fall back to standard "
                "fields only — no headcount, HQ or LinkedIn from this org's own "
                "fields — and the ICP test would judge companies on data that was "
                "never fetched. Resolve one with `quorom resolve-fields`."
            )
        sf.fields = FieldMap(field_map)
        for line in fieldmap_mod.describe_lines(field_map):
            log(f"[i] Field map: {line}")

        # Step 1 — the week's external attendees
        rows = db.week_attendees(conn, cfg)
        rows, suppressed = people_mod.suppress_non_contacts(rows)
        if suppressed:
            log(f"[i] Suppressed {len(suppressed)} non-contact(s): {', '.join(suppressed)}")

        # Step 2 — distinct people, grouped by company domain
        people = people_mod.dedupe_people(rows)
        companies = people_mod.group_companies(people)
        log(
            f"[*] {len(rows)} attendee-rows → {len(people)} distinct people, "
            f"{len(companies)} companies"
        )

        # Step 3 — reconcile against the CRM
        reconciled = [people_mod.reconcile(p, sf, hs) for p in people]
        total = len(reconciled)
        with_mobile = sum(1 for r in reconciled if r.get("mobile_in_crm"))
        with_linkedin = sum(1 for r in reconciled if r.get("linkedin_in_crm"))
        log(f"[*] Mobile in CRM: {with_mobile}/{total} — {total - with_mobile} gaps")
        log(f"[*] LinkedIn in CRM: {with_linkedin}/{total}")

        # Step 4 — company coverage (triage). The profile it filters on was
        # read and required at the top of this block.
        log(f"[*] Building company coverage for {len(companies)} companies...")
        coverage = coverage_mod.build_coverage(cfg, companies, profile, sf, hs, log=log)

        type_counts = coverage_mod.observed_account_types(coverage)
        log(f"[*] Account.Type values observed: {type_counts}")

        targets = [c for c in coverage if c["is_target"]]
        if cfg.customer_account_types:
            fits = sum(1 for c in coverage if c["meets"] == "yes")
            gated = [c["domain"] for c in coverage if c["meets"] == "yes" and c["is_customer"]]
            log(
                f"[*] ICP fit: {fits} meet the profile; {len(targets)} after the "
                f"Account.Type gate {list(cfg.customer_account_types)}"
            )
            if gated:
                log(f"[i] Gated as existing customers: {', '.join(gated)}")
        else:
            log(
                f"[*] ICP fit: {len(targets)} companies (employee band + HQ geography). "
                "Account.Type captured for context, not used as a filter."
            )

        # Step 5 — the stakeholder list
        terms = coverage_mod.seniority_terms(profile)
        history = db.met_history(conn, cfg, [c["domain"] for c in targets])
        log(
            f"[*] Meeting history: {len(history)} distinct people ever met across "
            f"{len(targets)} target companies"
        )
        stakeholders, bench_raw = stakeholders_mod.build(cfg, coverage, terms, history, sf)
        gaps = workbook_mod.count_gaps(stakeholders)
        log(
            f"[*] Stakeholder list: {len(stakeholders) - gaps} people across "
            f"{len(targets)} companies ({gaps} with no senior CRM contact)"
        )

        describe = sf.describe_contact() if sf.configured else {"checked": False}
        if describe.get("checked"):
            log(f"[*] Contact.describe: {describe['field_count']} fields")

    # Step 6 — emit
    week = start[:10]
    xlsx_path = os.path.join(cfg.output_dir, f"weekly_stakeholder_map_{week}.xlsx")
    workbook_mod.build_workbook(cfg, reconciled, coverage, suppressed, stakeholders, xlsx_path)
    log(f"[✓] Wrote {xlsx_path}")

    json_path = os.path.join(cfg.output_dir, f"stakeholder_inputs_{week}.json")
    workbook_mod.dump_inputs(
        json_path,
        {
            "week_start": week,
            "account": cfg.account,
            "focus_profile": profile,
            "crm_field_map": field_map,
            "seniority_terms": terms,
            "account_type_values_observed": type_counts,
            "customer_gate_patterns": list(cfg.customer_account_types),
            "coverage": coverage,
            "met_history": {
                k: {kk: str(vv) for kk, vv in v.items()} for k, v in history.items()
            },
            "sf_bench": bench_raw,
            "stakeholders": stakeholders,
            "contact_describe": describe,
        },
    )
    log(f"[✓] Wrote {json_path}")

    html_path = view_mod.render(xlsx_path, cfg.account)
    log(f"[✓] Wrote {html_path}")

    return {"xlsx": xlsx_path, "json": json_path, "html": html_path}
