"""Step 4 — company coverage. Triage: which companies warrant a map.

Serves every column of tab 3, and the ICP filter that decides which companies
reach tab 5's stakeholder list.
"""

from __future__ import annotations

from typing import Optional

from .. import geography
from ..config import Config
from ..crm.hubspot import HubSpot
from ..crm.salesforce import Salesforce

# Focus-profile seniority levels expanded into the title fragments a CRM
# actually contains. The profile says "vp"; Salesforce says "SVP", "Vice
# President". These began as a tier rule that assigned an outreach action per
# person; that was removed 2026-08-24. The matching survives because the
# ordering still needs it.
SENIORITY_KEYWORDS = {
    "cro": ["CRO", "Chief Revenue"],
    "cxo": ["Chief", "CEO", "CFO", "CTO", "COO", "CMO"],
    "c-level": ["Chief", "CEO", "CFO", "CTO", "COO", "CMO"],
    "vp": ["VP", "Vice President", "SVP", "EVP"],
    "director": ["Director", "Head of"],
    "founder": ["Founder", "Owner"],
    "manager": ["Manager"],
}

def seniority_terms(profile: dict) -> list[str]:
    terms: list[str] = []
    for level in profile.get("focus_seniority") or []:
        terms += SENIORITY_KEYWORDS.get(str(level).strip().lower(), [str(level)])
    return terms or ["VP", "Vice President", "Chief", "Director", "Head of"]


def meets_profile(profile: dict, employees, country: str) -> tuple[bool, str]:
    """The ICP test: employee band and HQ geography. Returns (ok, why-not).

    `country` is the HQ country on its own, not the joined display string. The
    test that preceded this one substring-matched a country list against
    "city, state, country", which is why the list held " us" with a leading
    space — to stop it matching inside "Australia".

    Two failures, kept apart: a country outside the selection is a decision the
    profile made, and no country at all is missing CRM data. They read the same
    before this, and a reader could not tell which they were looking at.
    """
    # An absent profile passing everything is why run_weekly refuses to start
    # without one (MissingFocusProfile). Kept as the answer for a caller that
    # has no profile to give, not as a mode the weekly run can reach.
    if not profile:
        return True, ""
    reasons: list[str] = []
    try:
        emp = int(employees)
    except (TypeError, ValueError):
        emp = None

    emin, emax = profile.get("employee_count_min"), profile.get("employee_count_max")
    if emp is None:
        reasons.append("no size")
    else:
        if emin and emp < emin:
            reasons.append(f"<{emin} emp")
        if emax and emp > emax:
            reasons.append(f">{emax} emp")

    selections = geography.parse_selections(profile.get("hq_geographies"))
    if selections:
        if not str(country or "").strip():
            reasons.append("HQ unknown")
        elif not geography.matches(selections, country):
            reasons.append(f"HQ not {geography.label(selections)}")

    return (not reasons), "; ".join(reasons)


def is_customer(cfg: Config, account_type: Optional[str]) -> bool:
    """The optional Account.Type gate, OFF unless configured.

    Type is a per-org picklist, so this matches substrings rather than
    hardcoding labels, and a run dumps the values it actually observed before
    the gate is applied. Off by default because Type is commonly not maintained
    as a lifecycle field: on one real week of 39 companies, gating on it
    collapsed 16 ICP-fit companies to 1.
    """
    t = (account_type or "").strip().lower()
    if not t or not cfg.customer_account_types:
        return False
    return any(p in t for p in cfg.customer_account_types)


def build_coverage(
    cfg: Config,
    companies: dict[str, dict],
    profile: dict,
    sf: Salesforce,
    hs: HubSpot,
    log=print,
) -> list[dict]:
    terms = seniority_terms(profile)
    coverage: list[dict] = []

    for domain in companies:
        stats = sf.domain_stats(domain, terms)
        firmo = sf.account_firmographics(stats.get("account_id"))
        ok, why = meets_profile(profile, firmo.get("employees"), firmo.get("country"))
        account_type = firmo.get("account_type", "")
        customer = is_customer(cfg, account_type)

        coverage.append(
            {
                "domain": domain,
                "name": firmo.get("name", ""),
                "employees": firmo.get("employees", ""),
                "hq": firmo.get("hq", ""),
                "account_type": account_type,
                "meets": "yes" if ok else (why or "no"),
                # The customer gate applies to the ICP-fit count, not only to the
                # shortlist — otherwise the triage number overcounts fit.
                "target": (
                    "yes"
                    if (ok and not customer)
                    else (
                        f"no — customer (Type: {account_type})"
                        if customer
                        else f"no — {why or 'profile'}"
                    )
                ),
                "is_target": bool(ok and not customer),
                "is_customer": customer,
                "met": len(companies[domain]["people"]),
                "sf_total": stats.get("sf_total", 0),
                "sf_senior": stats.get("sf_senior", 0),
                "hs_total": hs.count_domain(domain),
            }
        )

    return coverage


def observed_account_types(coverage: list[dict]) -> dict[str, int]:
    """The distinct Account.Type values AS OBSERVED, counted before any gate is
    applied — so the gate can be configured from a customer's real picklist
    rather than assumed labels."""
    counts: dict[str, int] = {}
    for c in coverage:
        key = c.get("account_type") or "(blank)"
        counts[key] = counts.get(key, 0) + 1
    return counts
