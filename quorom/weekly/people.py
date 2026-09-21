"""Steps 2 and 3 — distinct people, and their reconciliation against the CRM.

Step 2 serves: one row per person on tab 1 rather than one per meeting attended,
and the company keys tabs 3 and 4 are built on.
Step 3 serves: tab 1's Title / LinkedIn? / Mobile in CRM? / Flag, and tab 2's
In HubSpot? / In Salesforce?.
"""

from __future__ import annotations

import re
from typing import Optional

from ..crm.contact import Contact
from ..crm.fieldmap import NOT_CHECKED
from ..crm.hubspot import HubSpot
from ..crm.salesforce import Salesforce

# Local parts that indicate a shared mailbox rather than a person. A role inbox
# is not someone to enrich; it is someone to verify.
ROLE_LOCALPARTS = frozenset(
    {
        "support", "info", "sales", "jobs", "hello", "contact", "admin", "team",
        "help", "billing", "procurement", "careers", "hr", "marketing", "noreply",
        "no-reply", "office", "accounts", "finance", "legal", "press", "media", "it",
    }
)


def person_flag(name: Optional[str], email: Optional[str]) -> str:
    """Name-less rows are PEOPLE, not noise — they need their identity filled in.

    The address is checked first, and regardless of whether a name came with it.
    A role inbox frequently arrives named — a meeting source will happily label
    `amer-bdr@` as "AMER BDR", and a real person's name can sit on a shared
    `jobs@` address — and treating a name as proof of a person meant the
    shared-inbox flag never fired for either. "Is this someone to add to the
    CRM" is the question tab 2 exists to answer, so getting it wrong there is
    the whole column being wrong.
    """
    if email:
        tokens = re.split(r"[._-]", email.split("@", 1)[0].lower())
        if any(t in ROLE_LOCALPARTS for t in tokens):
            return "shared inbox — verify"
    if name and name.strip():
        return ""
    return "needs enrichment"


def suppress_non_contacts(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Meeting bots and tools have neither email nor domain — nothing to act on.

    Suppressed visibly: the names come back so the workbook can list them at the
    foot of tab 2 rather than quietly dropping them.
    """
    suppressed = sorted(
        {(r.get("attendee_name") or "(unnamed)") for r in rows if not (r.get("email") and r.get("domain"))}
    )
    kept = [r for r in rows if r.get("email") and r.get("domain")]
    return kept, suppressed


def dedupe_people(rows: list[dict]) -> list[dict]:
    """Collapse attendee-meeting rows to distinct people, keyed on lowercased email.

    Rows with no email stay distinct — they cannot be merged safely by name, and
    each is a gap worth reporting.
    """
    index: dict = {}
    people: list[dict] = []
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        key = email or (
            f"__nameonly__:{r.get('attendee_name')}|{r.get('domain')}|{r.get('meeting_id')}"
        )
        if key in index:
            p = index[key]
            title = r.get("meeting_title")
            if title and title not in p["meetings"]:
                p["meetings"].append(title)
            continue
        p = {
            "attendee_name": r.get("attendee_name"),
            "email": email or None,
            "domain": r.get("domain"),
            "domain_kind": r.get("domain_kind"),
            "meetings": [r["meeting_title"]] if r.get("meeting_title") else [],
            "flag": person_flag(r.get("attendee_name"), email or None),
        }
        index[key] = p
        people.append(p)
    return people


# Do NOT hard-exclude companies by domain. "Companies met this week" legitimately
# includes both customers and vendors — gong.io and hubspot.com are both. Whether
# a company is a fresh engagement target is an account-type question answered
# on tab 3, not by dropping the row here.
def group_companies(people: list[dict]) -> dict[str, dict]:
    companies: dict[str, dict] = {}
    for p in people:
        domain = p.get("domain") or "(no-domain)"
        companies.setdefault(domain, {"domain": domain, "people": []})["people"].append(p)
    return companies


def company_mismatch(domain: Optional[str], crm_company: Optional[str]) -> bool:
    """Does the CRM company look unrelated to the domain we met them on?

    NOT WIRED UP, deliberately, and called from nowhere. Turning it into a Flag
    value would add a column value the spec never asked for, and "possibly
    attached to the wrong company" is the sort of judgement the artifact is
    supposed to leave to the reader.

    Kept because part (b) of the CRM check in the root README — is the contact
    associated with the right company — will need something like it, and this is
    the shape it would take. It ships wired up when that read path is designed,
    not before.
    """
    if not domain or not crm_company:
        return False
    label = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
    comp = re.sub(r"[^a-z0-9]", "", crm_company.lower())
    if not label or not comp:
        return False
    return label not in comp and comp[:5] not in label


def _linkedin_presence(sf: Salesforce, contact: Optional[Contact]):
    """Four answers, because there are four situations.

    True/False — the CRM has a LinkedIn field and this person does or does not
    have one on file. None — the CRM has no such field at all, which the column
    states rather than rendering as an absent URL. NOT_CHECKED — no CRM was
    configured, so nothing was asked about this person at all.

    That last one used to answer False, which rendered as a blank cell
    indistinguishable from "we looked and they have no LinkedIn". This
    function's own docstring named that as the conflation tab 2 had fixed, and
    deferred it. It is no longer deferred.
    """
    if not sf.configured:
        return NOT_CHECKED
    if not sf.linkedin_available:
        return None
    return bool(contact.linkedin) if contact else False


def reconcile(person: dict, sf: Salesforce, hs: HubSpot) -> dict:
    """One attendee against whichever CRMs are configured. Salesforce wins on
    Title.

    Both adapters hand back a `Contact`, so nothing here names a field in either
    system — which is what lets a third CRM be added without touching this file.
    """
    email = person.get("email")
    hs_rec = hs.contact_by_email(email) if email else None
    sf_rec = sf.contact_by_email(email) if email else None

    # Whether any CRM was asked at all. Every column below that reports what a
    # CRM holds has to distinguish "asked, and the answer is no" from "never
    # asked" — otherwise the run asserts facts about people nobody looked up.
    crm_queried = sf.configured or hs.configured

    sf_title = sf_rec.title if sf_rec else ""
    hs_title = hs_rec.title if hs_rec else ""
    title = sf_title or hs_title

    # The meeting source often has no name for an attendee it has an address
    # for, while the CRM record this function just fetched has one. Taking the
    # title from that record and not the name reported "needs name" for people
    # the run had already looked up and could see — the same person appearing
    # blank on tab 1 and correctly named on tab 4. Salesforce wins, HubSpot is
    # the fallback, same precedence as the title beside it.
    crm_name = (sf_rec.name if sf_rec else "") or (hs_rec.name if hs_rec else "")
    name = person.get("attendee_name") or crm_name

    flags: list[str] = []
    base = person.get("flag", "")
    if base == "shared inbox — verify":
        flags.append(base)  # a role inbox is not a person to enrich
    else:
        missing = []
        if not (name and str(name).strip()):
            missing.append("name")
        # A missing title is only a finding if a CRM was asked for one. With no
        # CRM configured `title` is empty for everyone, and flagging "needs
        # title" on every named attendee reports a gap in a system that was
        # never consulted. The name check stays either way — that comes from the
        # meeting, not the CRM.
        if crm_queried and not title:
            missing.append("title")
        if missing:
            flags.append("needs " + " + ".join(missing))

    # These two flags compare one CRM with the other, so they exist only when
    # both were asked. With one configured, "title only in Salesforce" fired on
    # every row that had a title and on none without — it meant "has a title",
    # which the Title column already says. An unconfigured CRM returns no
    # record, which is not the same as a record with no title.
    if sf.configured and hs.configured:
        if sf_title and hs_title and sf_title.lower() != hs_title.lower():
            flags.append(f"title differs (SF: {sf_title} / HS: {hs_title})")
        elif (bool(sf_title) != bool(hs_title)) and (sf_title or hs_title):
            flags.append("title only in " + ("Salesforce" if sf_title else "HubSpot"))

    return {
        **person,
        "attendee_name": name,
        "in_hubspot": bool(hs_rec) if hs.configured else None,
        # None means not checked — never conflated with "not found".
        "in_salesforce": bool(sf_rec) if sf.configured else None,
        "title": title,
        # Presence only. The number itself never enters the artifact — and with
        # no CRM asked there is no presence to report, rather than an absence.
        "mobile_in_crm": (
            bool((sf_rec and sf_rec.mobile) or (hs_rec and hs_rec.mobile))
            if crm_queried
            else NOT_CHECKED
        ),
        "linkedin_in_crm": _linkedin_presence(sf, sf_rec),
        "flag": "; ".join(flags),
    }
