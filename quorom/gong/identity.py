"""Identity resolution — ported from v0 `src/lib/shared/deduplicate-attendees.ts`.

Collapses attendee sightings onto canonical person records. An attendee is one
appearance at one meeting; a person is a human, who may appear under more than
one email address over time.

Two departures from v0, both forced by v1's schema:

  * v0 wrote `people.company_domain`. v1 has no such column — company grouping
    is by `attendees.domain` and nothing joins a company table (see the root
    README, build item 1).

  * v0 inserts into `person_attendees` with no uniqueness constraint.
    migrations/0002 adds `unique (person_id, attendee_id)`, so this uses
    ON CONFLICT DO NOTHING. Without it, re-importing an overlapping date range
    fails on the second run rather than the first — the failure mode that makes
    a backfill look fine and then breaks the overnight job a day later.
"""

from __future__ import annotations

from typing import Optional, Sequence

import psycopg


def deduplicate_attendees(
    conn: psycopg.Connection, attendees: Sequence[dict], account_id: str
) -> int:
    """Link a call's attendees to person records. Returns people created.

    `attendees` are rows just inserted, each with id / email / name /
    domain_kind.
    """
    # Internal attendees are employees — never resolved to people.
    eligible = [a for a in attendees if a.get("domain_kind") != "internal"]
    if not eligible:
        return 0

    with_email = [a for a in eligible if a.get("email")]
    without_email = [a for a in eligible if not a.get("email")]

    emails: list[str] = list(dict.fromkeys(a["email"].lower() for a in with_email))
    email_to_person: dict[str, str] = {}
    created = 0

    with conn.cursor() as cur:
        # 1. Existing identifiers for these emails, in one query.
        if emails:
            cur.execute(
                "select email, person_id from person_identifiers "
                "where account_id = %s and email = any(%s)",
                (account_id, emails),
            )
            email_to_person = {r[0]: str(r[1]) for r in cur.fetchall()}

        # 2. A person for every email not seen before.
        unseen = [e for e in emails if e not in email_to_person]
        if unseen:
            name_for = {}
            for a in with_email:
                name_for.setdefault(a["email"].lower(), a.get("name"))

            # ON CONFLICT DO NOTHING covers the race where two runs create the
            # same person at once; the re-query below picks up either winner.
            cur.executemany(
                "insert into people (account_id, email, name, unmatched) "
                "values (%s, %s, %s, false) on conflict (account_id, email) do nothing",
                [(account_id, e, name_for.get(e)) for e in unseen],
            )
            cur.execute(
                "select id, email from people where account_id = %s and email = any(%s)",
                (account_id, unseen),
            )
            for pid, email in cur.fetchall():
                if email:
                    email_to_person[email] = str(pid)
                    created += 1

            cur.executemany(
                "insert into person_identifiers (person_id, account_id, email) "
                "values (%s, %s, %s) on conflict (account_id, email) do nothing",
                [
                    (email_to_person[e], account_id, e)
                    for e in unseen
                    if e in email_to_person
                ],
            )

        # 3. An attendee with no email cannot be deduplicated — no identifier to
        #    key on — so each sighting gets its own unmatched person record.
        #    These are the name-only rows the artifact reports as explicit gaps.
        unmatched_person: dict[str, str] = {}
        for a in without_email:
            cur.execute(
                "insert into people (account_id, name, unmatched) values (%s, %s, true) "
                "returning id",
                (account_id, a.get("name")),
            )
            row = cur.fetchone()
            if row:
                unmatched_person[a["id"]] = str(row[0])
                created += 1

        # 4. Link every eligible attendee to its person.
        links: list[tuple[str, str]] = []
        for a in with_email:
            pid = email_to_person.get(a["email"].lower())
            if pid:
                links.append((pid, a["id"]))
        for a in without_email:
            pid = unmatched_person.get(a["id"])
            if pid:
                links.append((pid, a["id"]))

        if links:
            cur.executemany(
                "insert into person_attendees (person_id, attendee_id) values (%s, %s) "
                "on conflict (person_id, attendee_id) do nothing",
                links,
            )

    return created


def resolved_email_key(
    conn: psycopg.Connection, account_id: str, email: str
) -> Optional[str]:
    """The person id an email resolves to, or None.

    Not used by the weekly run yet — MET_HISTORY_SQL still groups by email. This
    is the seam the history query grows into when the identity read path lands.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select person_id from person_identifiers where account_id = %s and email = %s",
            (account_id, email.lower()),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None
