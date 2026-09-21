"""Step 6 — emit. Four tabs, provenance on every row.

Nothing is written back to any system. The workbook and the JSON dump are the
only outputs, and the dump redacts MobilePhone to a boolean: sensitive contact
fields pass through to the CRM, never into a Quorom store.
"""

from __future__ import annotations

import json
import os

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from ..config import Config
from ..crm.fieldmap import NOT_AVAILABLE, NOT_CHECKED
from .stakeholders import NO_SENIOR_CONTACT

HEADER_FILL = "2F5B7C"


def _sheet(wb: Workbook, title: str, headers: list[str]):
    ws = wb.create_sheet(title)
    ws.append(headers)
    font = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor=HEADER_FILL)
    for cell in ws[1]:
        cell.font = font
        cell.fill = fill
    ws.freeze_panes = "A2"
    return ws


def _linkedin_cell(value) -> str:
    """None is not False, and neither is NOT_CHECKED. A CRM with no LinkedIn
    field says so in the cell, a run with no CRM says *that*, and only a real
    False renders blank — so an empty column cannot be read as 'nobody has
    one'."""
    if value == NOT_CHECKED:
        return NOT_CHECKED
    if value is None:
        return NOT_AVAILABLE
    return "yes" if value else ""


def _mobile_cell(value) -> str:
    """A plain yes/no about what the CRM holds, plus "not checked" when no CRM
    was asked at all.

    This used to read "GAP", in red. The column is a fact about a contact
    record, not a defect in one, and a page of red against rows where nothing
    was wrong made the whole artifact read as broken.
    """
    if value == NOT_CHECKED:
        return NOT_CHECKED
    return "yes" if value else "no"


def _checked_against(cfg: Config) -> str:
    """Tab 2's caption line naming the one CRM it was checked against, or "".

    This used to be a Source column holding the same value on every row, under
    the header that means "where this person came from" on tab 1 — so a tab of
    people not in Salesforce read "salesforce" beside each of them. A run-wide
    fact is stated once, in the caption, the way tab 3 states its ICP test.

    With both CRMs configured the "In …?" columns already say it per row, and
    with none the tab has no rows to explain. The names are the vendors' own,
    which is fine in a line that reports provenance — what is not fine is
    naming one that was not consulted.
    """
    names = []
    if cfg.hubspot.configured:
        names.append("HubSpot")
    if cfg.salesforce.configured:
        names.append("Salesforce")
    return f"Checked against {names[0]}." if len(names) == 1 else ""


def _profile_sentence(profile: dict, geo_label: str) -> str:
    """The ICP test in the reader's words, using their own numbers.

    This used to read "the employee band and HQ geography from your focus
    profile", which names a concept the reader of the file has never heard of
    and then declines to say what it contains. The run holds the values; a
    reader looking at a column of yes and no needs to know what the test was,
    and nothing else on the page tells them.
    """
    lo = profile.get("employee_count_min")
    hi = profile.get("employee_count_max")
    if lo and hi:
        band = f"{lo:,}–{hi:,} employees"
    elif lo:
        band = f"{lo:,}+ employees"
    elif hi:
        band = f"up to {hi:,} employees"
    else:
        band = "any size"
    return f"Meets profile? = {band}, HQ in {geo_label}."


def build_workbook(
    cfg: Config,
    reconciled: list[dict],
    coverage: list[dict],
    suppressed: list[str],
    stakeholders: list[dict],
    out_path: str,
    profile: dict,
    geo_label: str,
) -> None:
    wb = Workbook()
    wb.remove(wb.active)

    # Tab 1 — Met this week
    #
    # Three of these columns report what a CRM holds — the title, the LinkedIn
    # presence and the mobile presence. With no CRM configured none of them was
    # asked, so they are dropped rather than filled, exactly as tabs 2 and 3
    # drop the columns of a provider that was never queried. The tab itself
    # survives: who attended is answerable from the meeting source alone, which
    # is what makes this different from tab 2.
    #
    # Dropped rather than rendered "not checked" because a whole column of it on
    # every row is noise, and the absent header says the same thing once. The
    # distinction still exists in the data — reconcile() emits NOT_CHECKED — so
    # nothing downstream has to re-derive it.
    crm_on = cfg.salesforce.configured or cfg.hubspot.configured
    ws1 = _sheet(
        wb,
        "1 - Met this week",
        # "Title (CRM)", not "Title (SF)". The value already comes from either
        # CRM — Salesforce wins, HubSpot is the fallback — so "(SF)" was
        # imprecise even with Salesforce configured, and names a system that was
        # never called without it. Which system holds a differing title is
        # already stated in Flag, and the next column is "Mobile in CRM?".
        ["Name", "Email"]
        + (["Title (CRM)", "LinkedIn?", "Mobile in CRM?"] if crm_on else [])
        + ["Flag", "Source"],
    )
    for r in reconciled:
        row = [r.get("attendee_name"), r.get("email", "")]
        if crm_on:
            row += [
                r.get("title", ""),
                _linkedin_cell(r.get("linkedin_in_crm")),
                _mobile_cell(r.get("mobile_in_crm")),
            ]
        ws1.append(row + [r.get("flag", ""), "gong"])

    # Tab 2 — Missing from CRM
    #
    # A CRM that was not configured was not queried, so it gets no column at
    # all rather than a column of "not checked".
    #
    # **And with only one configured, neither does it.** Every row on this tab
    # is here *because* it is missing from a CRM, so with a single CRM the
    # column is the word NO repeated down the page — the sheet's own title
    # already said it. The columns earn their place only when both are on,
    # which is the case they exist for: "in HubSpot but not Salesforce" is
    # actionable, and a single merged "In CRM?" would throw that away.
    #
    # No Source column, for the same reason: it was the same value on every row.
    # Which CRM the tab was checked against is a caption line instead.
    hs_on = cfg.hubspot.configured
    sf_on = cfg.salesforce.configured
    both_crms = hs_on and sf_on
    ws2 = _sheet(
        wb,
        "2 - Missing from CRM",
        ["Name", "Email", "Company (domain)"]
        + (["In HubSpot?", "In Salesforce?"] if both_crms else [])
        + ["Flag"],
    )
    for r in reconciled:
        in_sf = r.get("in_salesforce")
        in_hs = r.get("in_hubspot")
        # None is "not checked", and only ever arises for a CRM that is
        # unconfigured — whose column is not rendered. So a rendered cell is
        # always a real yes/no, and "not checked" never reaches this tab.
        if in_hs is False or in_sf is False:
            flag = r.get("flag", "")
            # "needs name/title" is redundant in a gap report — the row IS the gap.
            flag = flag if "shared inbox" in flag else ""
            row = [r.get("attendee_name"), r.get("email", ""), r.get("domain")]
            if both_crms:
                row += ["yes" if in_hs else "NO", "yes" if in_sf else "NO"]
            ws2.append(row + [flag])
    checked = _checked_against(cfg)
    if checked or suppressed:
        ws2.append([])
    if checked:
        ws2.append([checked])
    if suppressed:
        ws2.append(
            [
                "Suppressed as non-contacts (no email/domain — likely meeting bots): "
                + ", ".join(suppressed)
            ]
        )

    # Tab 3 — Company coverage (triage)
    #
    # Same rule as tab 2, applied to counts: a provider that was not queried
    # contributes no column. A count column has to stay numeric to be sortable
    # and summable — writing "not checked" into it would turn the whole column
    # to text and quietly break sorting on the tab whose job is triage — so the
    # absence is expressed by dropping the column rather than by a value in it.
    ws3 = _sheet(
        wb,
        "3 - Company coverage",
        ["Company", "Company name", "Employees", "HQ", "Account type",
         "Meets profile?", "Met this wk"]
        + (["SF contacts", "SF focus-senior"] if sf_on else [])
        + (["HubSpot contacts"] if hs_on else []),
    )
    for c in sorted(coverage, key=lambda x: (not x.get("is_target"), -x.get("met", 0))):
        row = [
            c["domain"], c.get("name", ""), c.get("employees", ""), c.get("hq", ""),
            c.get("account_type", "") or "(blank)", c.get("meets", ""), c.get("met", 0),
        ]
        if sf_on:
            row += [c.get("sf_total", 0), c.get("sf_senior", 0)]
        if hs_on:
            row.append(c.get("hs_total", 0))
        ws3.append(row)
    ws3.append([])
    ws3.append(
        [
            _profile_sentence(profile, geo_label)
            + " A company with no employee count on file is excluded rather than"
            " given the benefit of the doubt. Account type is shown for context"
            " and is not used to filter."
        ]
    )

    # Tab 4 — Stakeholder list (the map)
    ws4 = _sheet(
        wb,
        "4 - Stakeholder list",
        ["Company", "Name", "Title", "Recent contact?", "LinkedIn", "Mobile in CRM?"],
    )
    for r in stakeholders:
        ws4.append(
            [r.get("company", ""), r.get("name", ""), r.get("title", ""),
             r.get("contact", ""), r.get("linkedin", ""), r.get("mobile", "")]
        )
    ws4.append([])
    # Two lines, and only what a reader needs to read a value in the table.
    # Design rationale, open questions and ticket references belong in the repo
    # and in Linear — not in a file that goes to a customer.
    ws4.append(
        [
            "People already in your CRM at these companies, most senior first. "
            "Others may exist who aren't in the CRM."
        ]
    )
    ws4.append(
        [
            f"Recent contact = a meeting, or activity logged in the CRM, in the last "
            f"{cfg.recent_days} days. Titles come from the CRM and may be out of date."
        ]
    )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    wb.save(out_path)


def dump_inputs(path: str, payload: dict) -> None:
    """Every input the run used, so the ordering can be re-tuned without going
    back to Salesforce."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)


def count_gaps(stakeholders: list[dict]) -> int:
    return sum(1 for r in stakeholders if r.get("name") == NO_SENIOR_CONTACT)
