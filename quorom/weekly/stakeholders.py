"""Step 5 — the stakeholder list. The map: which specific people at the companies
that passed triage.

Serves all six columns of tab 4: Company, Name, Title, Recent contact?, LinkedIn,
Mobile in CRM?.

Ordering is two rules and no weighting: most senior first, recent contact
breaking ties between equals. Capped per company — the cap is a feature.

No action is suggested per person. Real outreach starts with a connection, may
become a message, and may or may not become a meeting request; a column
declaring one action per row is wrong at the first step and asserts a decision
that has not been made. The list says who is worth considering and stops.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from ..config import Config
from ..crm.fieldmap import NOT_AVAILABLE
from ..crm.salesforce import Salesforce
from .coverage import seniority_terms  # noqa: F401  (re-exported for callers)

# Order matters: the VP test runs before the C-level test so "Vice President"
# never matches on the word 'president'.
_VP_STRING = re.compile(r"\b(vp|svp|evp|vice\s+president)\b", re.I)
_C_LEVEL = re.compile(r"\b(chief|ceo|cro|cfo|cto|coo|cmo|president|founder|owner)\b", re.I)
_C_LEVEL_EXCLUDE = re.compile(r"(chief\s+of\s+staff|deputy\s+chief|assistant\s+to\s+the)", re.I)
_DIRECTOR = re.compile(r"\b(director|head\s+of)\b", re.I)


def seniority_rank(title: Optional[str]) -> int:
    """3 C-level, 2 VP, 1 everything else. ORDERING ONLY.

    This used to return an outreach tier (connect / request meeting). That was
    removed 2026-08-24 — see the module docstring.
    """
    t = (title or "").strip()
    if not t:
        return 0
    if _C_LEVEL_EXCLUDE.search(t):  # "Chief of Staff" is not C-level here
        return 2
    if _VP_STRING.search(t):
        return 2
    if _C_LEVEL.search(t):
        return 3
    if _DIRECTOR.search(t):
        return 1
    return 1


def clean_title(title: Optional[str]) -> str:
    """LinkedIn headlines get pasted into Title — "Chief Revenue Officer (cro) |
    Cybersecurity | Cloud | Saas". Keep the role, drop the billboard. Seniority
    ordering still reads the raw value; this is display only."""
    t = (title or "").replace("\n", " ").strip()
    return t.split("|")[0].strip() if "|" in t else t


def _as_date(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except (ValueError, TypeError):
        return None


def recent_contact(cfg: Config, history: Optional[dict], last_activity) -> str:
    """One question, one answer.

    Contact is a meeting (from the product DB) or anything logged in the CRM
    (LastActivityDate, a Task+Event rollup that covers emails and calls without
    saying which). Recent means inside cfg.recent_days. The kind of contact is
    stated rather than judged, so a reader can discount a training session
    themselves instead of the code deciding for them.
    """
    cutoff = dt.date.today() - dt.timedelta(days=cfg.recent_days)
    met = _as_date((history or {}).get("last_met"))
    activity = _as_date(last_activity)

    if met and met >= cutoff:
        smallest = int((history or {}).get("smallest_meeting") or 0)
        kind = (
            f"group call, {smallest} attendees"
            if smallest > cfg.group_call_min
            else "met"
        )
        return f"yes — {kind} {met.isoformat()}"
    if activity and activity >= cutoff:
        return f"yes — CRM activity {activity.isoformat()}"

    last = max([d for d in (met, activity) if d], default=None)
    return f"no — last contact {last.isoformat()}" if last else "no — none on record"


NO_SENIOR_CONTACT = "— no senior contact in Salesforce —"


def build(
    cfg: Config,
    coverage: list[dict],
    terms: list[str],
    history: dict[str, dict],
    sf: Salesforce,
) -> tuple[list[dict], list[dict]]:
    """-> (rows for tab 4, the raw bench for the JSON dump)."""
    rows: list[dict] = []
    raw: list[dict] = []
    targets = [c for c in coverage if c.get("is_target")]

    for company in sorted(targets, key=lambda x: -x.get("met", 0)):
        bench = sf.senior_bench(company["domain"], terms)

        # The phone NUMBER is redacted out of the dump. Sensitive contact fields
        # pass through to the CRM and are never persisted here; presence is the
        # only thing the artifact needs.
        raw.append(
            {
                "domain": company["domain"],
                "bench_size": len(bench),
                # What the CRM actually returned, sensitive fields already
                # reduced by the adapter. Carried through opaquely so the dump
                # still lets the ranking be re-tuned without re-querying —
                # reading a field name out of it would put the coupling back.
                "bench": [c.provenance for c in bench],
            }
        )

        if not bench:
            # A company with no senior CRM contact is a stated gap, not an
            # omission — the reader needs to see that we looked.
            rows.append(
                {
                    "domain": company["domain"],
                    "company": company.get("name") or company["domain"],
                    "name": NO_SENIOR_CONTACT,
                    "title": "",
                    "contact": "",
                    "linkedin": "",
                    "mobile": "",
                }
            )
            continue

        scored = []
        for person in bench:
            email = person.email.strip().lower()
            contact = recent_contact(cfg, history.get(email), person.last_activity)
            scored.append(
                {
                    "domain": company["domain"],
                    "company": company.get("name") or company["domain"],
                    "name": person.name,
                    "title": clean_title(person.title),
                    "contact": contact,
                    # None is the CRM having no LinkedIn field at all, which the
                    # column states; "" is this person having nothing in it.
                    "linkedin": (
                        NOT_AVAILABLE if person.linkedin is None else person.linkedin
                    ),
                    "mobile": "yes" if person.mobile else "GAP",
                    "_seniority": seniority_rank(person.title),
                    "_recent": contact.startswith("yes"),
                    "_email": email,
                }
            )

        scored.sort(key=lambda x: (-x["_seniority"], not x["_recent"]))
        rows.extend(scored[: cfg.shortlist_size])

    return rows, raw
