"""The enrichment pass — a provider's second opinion, set beside the CRM's.

Runs only when an enrichment provider is configured (see `quorom/enrich/`), and
changes nothing when one is not. Serves:

  tab 2  Name (provider), Title (provider) — for people not in the CRM
  tab 3  Employees (provider), HQ (provider), Profile check
  tab 4  Still at company?, Title (provider), LinkedIn (provider), and which
         companies reach the map at all (a disputed verdict does)
  tab 5  the review queue

Three sources, and none is the truth. The CRM is what the customer has; the
provider is a second opinion that can be stale too; LinkedIn is what a person
checks, and the one that settles it. So a provider value is **never** written
over a CRM value — it is shown beside it, and a disagreement becomes a row in
the review queue for a person to settle.

Agreement is not correctness either. A provider may be one of the sources the
CRM was filled from, in which case the two agreeing says little. The queue
therefore holds disagreements and missing values; it does not certify the rest.
"""

from __future__ import annotations

import re
from typing import Optional

from .coverage import meets_profile
from .people import company_mismatch, missing_from_crm
from .stakeholders import ICP_NOT_ASSESSED, NO_SENIOR_CONTACT

AGREES = "agrees"

_LINKEDIN_HANDLE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.I)


def not_found(provider) -> str:
    """The provider rule, as a cell: looked, and this provider has nothing.
    Never inferred, never blank, never filled from somewhere else."""
    return f"not found in {provider.display_name}"


class _Cached:
    """One lookup per email and per domain per run, whichever tab asks first.
    A person on tab 2 and tab 4 is one credit, not two."""

    def __init__(self, provider) -> None:
        self.provider = provider
        self._people: dict = {}
        self._companies: dict = {}
        self.people_looked_up = 0
        self.companies_looked_up = 0

    def person(self, email: str):
        key = (email or "").strip().lower()
        if key not in self._people:
            self._people[key] = self.provider.person_by_email(key) if key else None
            self.people_looked_up += 1 if key else 0
        return self._people[key]

    def company(self, domain: str):
        key = (domain or "").strip().lower()
        if key not in self._companies:
            self._companies[key] = self.provider.company_by_domain(key) if key else None
            self.companies_looked_up += 1 if key else 0
        return self._companies[key]


def start(provider) -> Optional[_Cached]:
    return _Cached(provider) if provider else None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _handle(url: str) -> str:
    m = _LINKEDIN_HANDLE.search(url or "")
    return m.group(1).lower().rstrip("/") if m else _norm(url)


# --- tab 3: companies ------------------------------------------------------ #


def companies(pass_: _Cached, coverage: list[dict], profile: dict) -> None:
    """Look up every company met, and compare ICP verdicts rather than numbers.

    A difference matters only if it changes the verdict: 250 against 275 is
    inside a 50–500 band either way, 480 against 520 flips it. So what is
    compared is the ICP test run on each source's own numbers.

    A disputed company goes onto the stakeholder list, marked. A wrong "no" is
    the invisible error — the company never reaches the map and nobody looks —
    so a dispute is resolved by a person, not by leaving it off.
    """
    name = pass_.provider.display_name
    for c in coverage:
        found = pass_.company(c.get("domain"))
        c["disputed"] = False
        if found is None:
            c["other_employees"] = None
            c["other_hq"] = ""
            c["verdict_check"] = not_found(pass_.provider)
            c["other_missing"] = True
            continue

        c["other_employees"] = found.employees
        c["other_hq"] = found.country
        ok, why = meets_profile(profile, found.employees, found.country)
        c["other_missing"] = found.employees is None or not found.country
        said = "yes" if ok else f"no ({why})"

        if not c.get("assessed", True):
            c["verdict_check"] = f"CRM not assessed — {name} says {said}"
        elif (c.get("meets") == "yes") == bool(ok):
            c["verdict_check"] = AGREES
        else:
            c["verdict_check"] = f"disputed — {name} says {said}"
            c["disputed"] = True


# --- tab 4: stakeholders --------------------------------------------------- #


def stakeholders(pass_: _Cached, rows: list[dict]) -> None:
    """Is each person still where the CRM says, and does the provider agree on
    title and LinkedIn?

    A detected move flags the row; it never removes it. The CRM record is what
    the customer has, and a name vanishing without explanation is worse than a
    name marked stale. The provider's title and LinkedIn are filled only where
    they differ from the CRM's — the caption says so.
    """
    name = pass_.provider.display_name
    for r in rows:
        if r.get("name") in (NO_SENIOR_CONTACT, ICP_NOT_ASSESSED) or not r.get("_email"):
            r["still_at"] = r["other_title"] = r["other_linkedin"] = ""
            continue
        p = pass_.person(r["_email"])
        if p is None:
            r["still_at"] = not_found(pass_.provider)
            r["other_title"] = r["other_linkedin"] = ""
            continue
        if not p.employer_domain:
            r["still_at"] = f"unclear — no current employer in {name}"
        elif p.employer_domain == (r.get("domain") or "").lower():
            r["still_at"] = "yes"
        else:
            r["still_at"] = f"no — now at {p.employer_name or p.employer_domain}"
        r["other_updated"] = p.updated
        # Someone who has moved holds a title somewhere else. Setting it beside
        # the CRM's would read as a disagreement about this job; the move is the
        # finding, and it is already stated.
        moved = r["still_at"].startswith("no —")
        r["other_title"] = (
            p.title if p.title and not moved and _norm(p.title) != _norm(r.get("title")) else ""
        )
        crm_linkedin = r.get("linkedin") or ""
        r["other_linkedin"] = (
            p.linkedin if p.linkedin and _handle(p.linkedin) != _handle(crm_linkedin) else ""
        )


# --- tab 2: people not in the CRM ----------------------------------------- #


def not_in_crm(pass_: _Cached, reconciled: list[dict]) -> None:
    """A name and title for people the CRM does not hold — the gap tab 2 exists
    to report, with the part a person needs to act on it."""
    for r in reconciled:
        if not missing_from_crm(r):
            continue
        if "shared inbox" in (r.get("flag") or ""):
            # A role inbox is not a person. Looking it up spends a credit on an
            # answer that cannot be right.
            r["other_name"], r["other_title"] = "not looked up — shared inbox", ""
            continue
        p = pass_.person(r.get("email"))
        if p is None:
            r["other_name"], r["other_title"] = not_found(pass_.provider), ""
        else:
            r["other_name"], r["other_title"] = p.name, p.title


# --- tab 5: the review queue ---------------------------------------------- #

QUEUE_ORDER = (
    "Profile fit disputed",
    "Headcount or HQ missing",
    "May have left",
    "Account may be linked to the wrong company",
    "Title differs",
    "LinkedIn differs",
)


def review_queue(pass_: _Cached, coverage: list[dict], rows: list[dict]) -> list[dict]:
    """Every item a person should settle, and nothing else.

    Written as a work queue rather than as CRM updates: Quorom writes nothing to
    the CRM, and whoever works through this list may not have CRM access at all.
    Each row says what to check and where.
    """
    queue: list[dict] = []

    def add(kind, company, who, crm, other, check):
        queue.append(
            {"kind": kind, "company": company, "who": who, "crm": crm, "other": other,
             "check": check}
        )

    for c in coverage:
        label = c.get("name") or c.get("domain")
        crm_side = f"{c.get('employees') or '?'} employees, HQ {c.get('hq') or '?'} — {c.get('meets')}"
        other_side = (
            f"{c.get('other_employees') if c.get('other_employees') is not None else '?'} "
            f"employees, HQ {c.get('other_hq') or '?'}"
        )
        if c.get("disputed"):
            add("Profile fit disputed", label, "", crm_side,
                f"{other_side} — {c['verdict_check'].split(' says ', 1)[-1]}",
                "Company LinkedIn page: headcount, HQ")
        elif c.get("assessed", True) and (
            c.get("other_missing") or "no size" in str(c.get("meets")) or "HQ unknown" in str(c.get("meets"))
        ):
            add("Headcount or HQ missing", label, "", crm_side,
                other_side if c.get("verdict_check") != not_found(pass_.provider) else not_found(pass_.provider),
                "Company LinkedIn page; fill in the CRM")
        if c.get("assessed", True) and c.get("name") and company_mismatch(c.get("domain"), c.get("name")):
            add("Account may be linked to the wrong company", label, "",
                f"account '{c.get('name')}' reached through {c.get('domain')}", "",
                "The account's Website field in the CRM")

    for r in rows:
        if not r.get("still_at") or r.get("still_at") == not_found(pass_.provider):
            continue
        who = r.get("name", "")
        company = r.get("company", "")
        if r["still_at"].startswith("no —"):
            add("May have left", company, who, f"at {company}",
                r["still_at"][len("no — "):] + (f" (updated {r['other_updated']})" if r.get("other_updated") else ""),
                "Their LinkedIn profile")
        if r.get("other_title"):
            add("Title differs", company, who, r.get("title") or "(none)", r["other_title"],
                "Their LinkedIn profile")
        if r.get("other_linkedin"):
            add("LinkedIn differs", company, who, r.get("linkedin") or "(none)", r["other_linkedin"],
                "Open both — one may be someone else")

    rank = {k: i for i, k in enumerate(QUEUE_ORDER)}
    queue.sort(key=lambda q: (rank.get(q["kind"], len(rank)), str(q["company"]).lower()))
    return queue
