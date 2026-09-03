# The pipeline

Six steps. Each one names the read path it serves — the column, tab or filter in
the stakeholder-map artifact that would be wrong or absent without it. A step
with no read path named is a step that should not exist.

This is the pipeline as it actually runs, written down rather than redesigned —
a description of working code, not of an intention.

The code lives in `quorom/` — one module per step, named for the step:

```
quorom/bootstrap.py         quorom init — the account row and the focus profile
quorom/config.py            every environment value, in one place
quorom/geography.py         regions, countries and the HQ comparison
quorom/db.py                the product DB and the three queries against it
quorom/domains.py           internal / external / personal classification
quorom/gong/                client.py · importer.py · identity.py      (step 0)
quorom/crm/                 salesforce.py · hubspot.py                 (steps 3-5)
                            fieldmap.py — the resolved field map      (step 0b)
                            contact.py — what an adapter hands back
quorom/weekly/              people.py (1-3) · coverage.py (4) ·
                            stakeholders.py (5) · workbook.py + view.py (6) ·
                            run.py — the sequence, and nothing else
quorom/cli.py               quorom init · resolve-fields · import · weekly
```

Sources are named per step: **DB** = your own Postgres (schema in
`migrations/`), **SF** = Salesforce, **HS** = HubSpot, **Gong** = the call
source, via the importer that fills DB.

---

## Step 0a — Init (once per deployment)

**Reads:** the command line, and `ACCOUNT_DOMAIN`.
**Writes:** DB `accounts`, `user_focus_profiles`.

The migrations create empty tables. `quorom init` creates the two rows that
everything else needs: the account (its name and internal domains) and an
active focus profile (employee band, HQ geographies, seniority levels). Without
the account, `quorom import` stops. Without the profile, `quorom weekly`
refuses to start — see step 4.

```bash
quorom init --internal-domains acme.com,acme.io \
            --employee-min 200 --employee-max 10000 \
            --geographies "North America" \
            --seniority c-level,vp,director
```

Re-running it with the same arguments writes nothing. Re-running it with a
different profile is refused: the profile decides which companies appear on the
map, so changing it is `--replace`, which supersedes the active version and
keeps the old one, inactive. A domain added later needs no `--replace`.

A seniority level the CRM matching does not know is warned about at this point
rather than discovered in an artifact — it would match nobody. A geography the
ICP test cannot act on is *refused* here rather than warned about
(`quorom/geography.py`); it used to be a warning, and a profile naming a region
the test did not know applied no geography filter at all.

---

## Step 0b — Resolve the CRM field map (once, then when the org changes)

**Reads:** the CRM's own description of `Account` and `Contact`, and one row
count per candidate field.
**Writes:** DB `crm_field_maps`.

Standard fields are portable; custom fields are not, and custom fields are where
the signal lives. A field that does not exist raises `INVALID_FIELD` and kills
the whole query rather than blanking a column, so a hardcoded custom name is a
run that dies at the next customer — and it is per-customer differentiation
living in code. **The repository holds patterns, never names** (README, "CRM
field map").

`quorom init` resolves the map; `quorom resolve-fields` re-resolves it when an
admin adds a field or a package is installed, superseding the active version and
keeping the old one so last week's artifact stays explicable.

Five logical fields, each named for the column it serves: `employee_count`,
`hq_country`, `hq_city`, `hq_state` on `Account`, and `linkedin_url` on
`Contact`. For each, the resolver matches every field's API name and label
against an include pattern, drops the ones an exclude pattern or the field's
type rules out, counts how many rows actually have each survivor populated, and
stores them **in count order**.

**A list per logical field, not a winner.** The first populated value wins at
read time. On one real org, three of the thirty-nine companies met in a single
week had an empty package country and a populated `BillingCountry`; a
single-name map would blank their HQ and drop one of them out of the ICP set.

**Counting alone is not enough.** On the same org the best-populated field
matching `/linkedin/` on `Contact` is the *company's* page, beating the
person's profile URL. Exclusions are as much a part of a pattern as
inclusions, and every rejection is stored with the rule that made it, so the
choice can be argued with rather than trusted.

Unresolved **optional** fields degrade their column to "not available in this
CRM" — only `linkedin_url` has no standard equivalent. An unresolved
**required** field stops the resolution: without a headcount field the ICP
employee band cannot be applied, and the run would report every company as a
fit.

Salesforce unconfigured means no map and no error: that run reads no CRM fields
at all. Salesforce configured with no map is fatal — every query would silently
fall back to standard fields only.

---

## Step 0 — Import (prerequisite, not part of a run)

**Reads:** Gong API (per-account credentials from the environment).
**Writes:** DB `meetings`, `attendees`, and — through the dedupe step —
`people`, `person_identifiers`, `person_attendees`.

`quorom import` with no arguments imports the last `RECENT_DAYS` days —
the same window `Recent contact?` is answered against (step 5). It is derived
rather than fixed so the two cannot drift: importing less than the recency
window would put "no" against people who were met inside it, and a deployment
should not have to pick a number to get started. `--from … --to …` extends the
history beyond it; `quorom import --yesterday` is the overnight run.

The counts it prints carry the elapsed time, because the question they get
asked is whether to extend the range — calls-in-range and the time they took
are what a year's backfill can be extrapolated from.

**No transcripts are stored.** The importer reads Gong's call and party
endpoints only; `meetings` has no transcript column and nothing downstream reads
one.

**Read path served:** everything downstream. It is the only step that writes.

**Why it persists rather than paging Gong live:** the stakeholder list reads
all-time history, not the week. A year of one organisation's calls runs to a
couple of thousand meetings and several thousand external attendee rows —
re-paging that on every weekly run is the wrong shape, and it would also discard
the attendance-vs-invitation record between runs.

### Idempotency, and why it matters

A backfill and an overnight run **will** overlap. `migrations/0002` puts
`unique (person_id, attendee_id)` on `person_attendees`, which turns a silent
double-write into an error.

That error does not appear on the run that creates the problem. The first
import succeeds. The second one, over any range that overlaps it, raises — so a
backfill looks clean on Friday and the overnight job dies on Saturday, with
nothing in between to suggest why.

The port therefore has idempotency at three levels, all in `quorom/gong/`:

| Write | Guard |
|---|---|
| `meetings` | `on conflict (account_id, provider, provider_id) do update` — re-importing refreshes title and timing rather than duplicating the call |
| `attendees` | a call whose meeting already has attendee rows is skipped whole |
| `people`, `person_identifiers` | `on conflict … do nothing` on the account+email keys |
| `person_attendees` | `on conflict (person_id, attendee_id) do nothing` |

`tests/test_import_and_weekly.py::test_reimport_is_idempotent` runs the same
range twice and asserts every table count is unchanged. It is there to fail if
any of the four guards is ever removed.

---

## Step 1 — Pull the week's external attendees

**Reads:** DB `meetings` ⋈ `attendees` ⋈ `accounts`, filtered to one week and
to `domain_kind = 'external'`.
**Cost:** none.

**Read path served:** determines which rows exist on **tab 1 (Met this week)**
and **tab 2 (Missing from CRM)** at all. Supplies `Name`, `Email`,
`Company (domain)`, and the meeting titles.

Attendees with neither email nor domain are suppressed as non-contacts (meeting
bots) and listed by name at the foot of tab 2 — suppressed visibly, not dropped.

---

## Step 2 — Dedupe to distinct people, group by domain

**Reads:** step 1's rows. No I/O.
**Cost:** none.

**Read path served:** one row per person on tab 1 rather than one per meeting
attended; and the company keys that tabs 3 and 4 are built on.

Deduplication is on lowercased email. Rows with no email stay distinct — they
cannot be merged safely by name, and each is a gap worth reporting. Each gets a
follow-up flag: `needs enrichment` for a real inbox, `shared inbox — verify`
for a role address.

**Known limitation, and where it gets fixed:** email-keyed grouping splits a
person who has changed address. Demonstrated on a fixture 2026-08-24: one
person seen as `dana.reyes@` and `d.reyes@` becomes two rows with
`last_met` 2026-08-19 and 2025-10-21 — so the `Recent contact?` column reads
`no` for someone met last week. Resolving the key through `person_identifiers`
collapses them to one row with the correct date. That query is written and
verified; wiring it in is the read path that justifies the identity tables
(see `migrations/0002_identity.sql`).

---

## Step 3 — Reconcile each attendee against the CRM

**Reads:** HS contacts by email; SF `Contact` by email — the standard fields
(`Id, Name, Title, MobilePhone, Email, AccountId, Account.Name`) plus whatever
the field map resolved for `Contact.linkedin_url` (step 0b).

Both adapters hand back a `Contact` — `{name, title, email, mobile, linkedin,
last_activity}` — never a CRM record. Those API names appear in this document
and in `crm/`, and nowhere under `weekly/`: a standard field name is as much a
coupling as a custom one, it is just spelled the same in every Salesforce org.
`mobile` is presence only, reduced inside the adapter so the number cannot reach
the JSON dump. `linkedin` is three-valued — a URL, `""` for nothing on file, and
`None` for a CRM with no such field, which is what tab 1 and tab 4 render as
"not available in this CRM".
**Cost:** none — customer-owned data in both systems.

**Read path served:**
- tab 1 — `Title (SF)`, `LinkedIn?`, `Mobile in CRM?`, `Flag`
- tab 2 — `In HubSpot?`, `In Salesforce?`, and which rows appear there at all.
  One column per CRM that was actually configured: an unqueried CRM is not a
  column of "not checked", it is not a column. Both are kept when both are on,
  because "in HubSpot but not Salesforce" is the answer the tab exists for.

Salesforce is the source of truth for `Title`; HubSpot is the fallback and the
disagreement between them is itself a flag (`title differs`, `title only in …`).
Mobile is presence only — the number is never read into the artifact and is
redacted to a boolean in the JSON dump.

No CRM sync and no CRM tables. Contacts are fetched at read time and compared in
context, which is what keeps the comparison current and the schema small.

---

## Step 4 — Company coverage (triage)

**Reads:** DB `user_focus_profiles` (the active profile) and `crm_field_maps`
(the resolved one); SF contact counts per email domain, plus the senior-title
count and one `AccountId`; SF `Account` firmographics — the standard
`Name, Type` plus every field the map resolved for `employee_count`, `hq_city`,
`hq_state` and `hq_country`; HS contact count per domain.
**Cost:** none.

**Read path served:** every column of **tab 3 (Company coverage)** —
`Company name`, `Employees`, `HQ`, `Account type`, `Meets profile?`,
`Met this wk`, `SF contacts`, `SF focus-senior`, `HubSpot contacts` — and the
ICP filter that decides which companies reach tab 4. The three count columns
appear only for a CRM that was configured: a count of contacts nobody counted
is a 0 that reads exactly like a company with none on file.

`Meets profile?` is the employee band and HQ geography from the focus profile.
**A run without an active profile stops here — before step 1, in fact.** An
absent profile makes the ICP test pass everything, so the run would complete,
the workbook would have its usual shape, and every company met that week would
be reported as a target; a reader could not tell that from a correct run. The
profile is read and required at the top of `run_weekly` so the failure costs a
second rather than every CRM call above it. `quorom init` creates one.
`Account type` is captured and displayed but is **not** a filter: across the 39
companies met in the 2026-08-17 week the only values present were
`Customer - Direct` (31), `Customer Lost` (3), `Freemium User` (4) and one blank,
and gating on it collapsed 16 ICP-fit companies to 1. The gate stays in the code
behind `CUSTOMER_ACCOUNT_TYPES`, off by default.

The firmographics query names no non-standard field: every one comes from the
resolved map (step 0b), so an org with no managed data package installed reads
`NumberOfEmployees` + `Billing*` without a line of code changing. That is
`quorom/crm/salesforce.py` contains no `__c` name, and a test asserts it.

`Meets profile?`'s geography half compares the HQ **country** as a whole value
against the profile's selections (`quorom/geography.py`). The test it replaced
substring-matched a country list against the joined "city, state, country"
display string, which is why that list carried `" us"` with a leading space — to
stop `us` matching inside `Australia`. Selections are `{level, value}` at region
or country level, three regions (North America, EMEA, APAC), and a bare string
reads as a region so profiles written before levels keep working. A region or
country the test does not know is refused at `quorom init` and again before a
run starts: it used to be accepted, apply no geography filter at all, and pass
every company met.

Two geography failures, kept apart on the row: `HQ not NA` is a country outside
the selection — a decision the profile made — and `HQ unknown` is no country in
the CRM at all. Both read `HQ not NA` before, and a reader could not tell which.

---

## Step 5 — Stakeholder list (the map)

**Reads:** DB all-time external meeting history for the target domains, with the
external-attendee count of each meeting; SF senior bench per domain
(`Name, Title, Email, MobilePhone, LastActivityDate` plus the resolved
`Contact.linkedin_url` candidates, title filtered by the focus profile's
seniority terms).
**Cost:** none.

**Read path served:** all six columns of **tab 4 (Stakeholder list)** —
`Company`, `Name`, `Title`, `Recent contact?`, `LinkedIn`, `Mobile in CRM?`.

Ordering is two rules, no weighting: most senior first, recent contact breaking
ties between equals. Capped at `SHORTLIST_SIZE` (3) per company — the cap is a
feature. A company with no senior CRM contact gets an explicit
`— no senior contact in Salesforce —` row rather than being omitted.

`Recent contact?` is one yes/no question. Contact is a meeting (from DB) or
anything logged in the CRM (`LastActivityDate`); recent is `RECENT_DAYS` (90).
A meeting with more than `GROUP_CALL_MIN` (8) external attendees is labelled a
group call on the row, so the reader discounts a training session rather than
the code doing it for them.

**No action is suggested per person.** The outreach sequence — connect, maybe
message, maybe meeting request — is undecided, so the artifact says who is worth
considering and stops.

**Not run here:** net-new discovery through an enrichment provider. It is not
part of the weekly file today. When it is added, the provider rule has teeth: an
unresolved person becomes an explicit "not found in &lt;provider&gt;" row, never
filled from elsewhere and never dropped.

**Not checked here:** whether each person is still at the company. The column is
absent rather than saying `not checked` on every row. An enrichment provider
could answer it; none is wired up.

---

## Step 6 — Emit

**Writes:** a local `.xlsx` (four tabs, provenance per row) and a JSON dump of
every input — focus profile, seniority terms, observed `Account.Type` values,
coverage, meeting history, the SF bench, the shortlist, and the `Contact`
describe.

**Read path served:** the artifact itself; and the JSON is what lets the ranking
be re-tuned without re-running Salesforce.

Nothing is written back to any system. `MobilePhone` is reduced to a boolean in
the dump — sensitive contact fields pass through to the CRM, never into a
Quorom store.

---

## Running it

```bash
pip install -e .
cp .env.example .env          # then fill it in
psql "$DATABASE_URL" -f migrations/0001_core.sql  # …and 0002, 0003, 0004

quorom init --internal-domains acme.com --employee-min 200 \
            --employee-max 10000 --geographies "North America" \
            --seniority c-level,vp,director        # once

quorom import                                    # the last RECENT_DAYS days
quorom import --from 2025-10-01 --to 2026-08-24   # a longer history
quorom import --yesterday                          # the overnight run
WEEK_START=2026-08-17 quorom weekly                # the artifact
```

`quorom weekly` writes three files into `OUTPUT_DIR`: the workbook, the JSON
dump of every input, and the single-page HTML view. It writes nothing anywhere
else.

**What the tests cover, and what they cannot.** `pytest` runs the importer and
the whole weekly sequence against a real Postgres with the real migrations and
a stubbed Gong, with **Salesforce and HubSpot deliberately unconfigured** —
which is how the unconfigured-provider path stays honest rather than
degrading into "NO" or into a count of 0. The CRM legs are typically unreachable from an agent session and have to be
verified on a machine that can reach them, by diffing a workbook against a
known-good run for the same week. Point `QUOROM_TEST_DSN` at a Postgres a test
may create databases on; without it the database tests skip rather than fail.

## Where it runs

Inside your own environment. Salesforce and HubSpot are typically unreachable
from an agent session — an egress proxy refuses CONNECT, and no token changes
that. Your database is reachable from wherever the pipeline runs, which is the
same environment.

Testing by hand uses a pasted Salesforce token that expires in ~2 hours
(`docs/salesforce-access.md` runbook). A deployed run uses the client-credentials
flow (`SF_TOKEN_URL` / `SF_CLIENT_ID` / `SF_CLIENT_SECRET`) — no paste, no
refresh ritual.

## What the pipeline does not do

No MCP tools. No web UI. No briefs, no deliverables, no Linear publishing, no
per-contact scoring, no transcript moments, no outbound sequencing. The read
surface is one file. Tools are earned by a demonstrated interactive read, and
none has been demonstrated yet.
