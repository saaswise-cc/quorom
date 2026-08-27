# Setting Quorom up

From nothing to a weekly stakeholder map. Written for someone who can run
commands and read an error, most likely working alongside an agent reading this
repository with them.

Read section 1 before anything else. It is the one part that, ignored, makes
everything after it come apart later rather than immediately.

---

## 1. The boundary

Two repositories are involved. Only one of them is yours to change.

**Upstream — this repository.** All of the code. You read it. You never edit it.

**Yours — a repository in your own version control.** Three things, and nothing
else:

| Yours | What it means |
|---|---|
| Configuration | The values that make this deployment yours — your domains, your ICP, your tuning |
| Secret *references* | The names of the secrets, not the secrets. Values live in your secret store. |
| Your deployment pipeline | How the code reaches a machine, and what runs it on a schedule |

**Why this matters more than it looks.** The instinct on arriving at a repo you
need to run is to fork it and start editing. A fork can take no update. Six
months later upstream has fixed something you are also hitting, and there is no
path to it that is not a manual merge of code you did not write. That outcome is
what this whole repository is shaped to avoid, which is why it is the first thing
stated rather than a footnote.

**The two things most likely to make you reach for the code are already
configuration.**

- *"Our Salesforce field is called something else."* Nothing in this repository
  names a non-standard Salesforce field. At setup, `quorom init` reads your
  org's own description of `Account` and `Contact`, matches fields against
  generic patterns, counts how many records actually have each one populated,
  and stores the result. Every query is then built from that map.
  `quorom resolve-fields` re-runs it when your admin adds a field.
  See `docs/supported-configuration.md`.
- *"Our ICP is different."* Employee band, HQ geography and the seniority bar
  are the focus profile — arguments to `quorom init`, stored in your database.

If you find something that genuinely requires a code change, that is an upstream
change. Raise it. Do not patch it locally: a local patch is a fork wearing a
smaller hat.

**No contributions are accepted** and pull requests are turned off. This is not
unfriendliness — see `LICENSE` and the README.

---

## 2. What you are setting up

Four things. The first three take minutes; the fourth is the rest of this guide.

1. **A Claude project** — where you and an agent do the setup and, afterwards,
   read the output.
2. **A Linear project** — where the work and the open questions are tracked.
3. **A repository in your own version control** — config, secret references,
   your pipeline. Per section 1.
4. **A running deployment** — a PostgreSQL database, the pipeline installed
   against it, and a schedule that runs it.

---

## 3. Before you start

Everything below is needed. Get them in hand first; discovering a missing one
halfway through step 7 costs more than checking now.

| You need | Why | How to check |
|---|---|---|
| **PostgreSQL 13 or later**, that the machine running the pipeline can reach | The product database. `gen_random_uuid()` is built in from 13. | `psql "$DATABASE_URL" -c "select version();"` |
| **Python 3.11 or later** on that machine | The pipeline is Python. | `python3 --version` |
| **`psql`** on whichever machine applies the migrations | Four SQL files to run | `psql --version` |
| **Gong API credentials** — an access key and secret | The meeting source. Everything downstream reads meetings imported from here. | Gong admin → API |
| **Outbound network to `api.gong.io`** from the machine that will run the import | The overnight job needs it too, not just your laptop | `curl -sI https://api.gong.io` |
| **Salesforce access** — see section 7 | The CRM half of the map: reconciliation, firmographics, the senior contact bench | |
| **A HubSpot private-app key** *(optional)* | Marketing contacts. Absent, those columns read "not checked" rather than "no". | |

**Salesforce is effectively required**, though the pipeline runs without it. The
stakeholder list is built entirely from Salesforce contacts, so without it you
get the meeting reconciliation and the company coverage, and a stakeholder tab
that is all gaps.

**It costs nothing to run.** Every field in the output comes from Gong,
Salesforce or HubSpot — data you already own. No enrichment provider is called.

---

## 4. Step 1 — Your repository

Create an empty repository in your own version control. What goes in it:

```
.env.example        # copied from upstream, filled in with YOUR values —
                    # names and non-secret values only, never a secret
deploy/             # your pipeline: however the code reaches a machine
schedule/           # your scheduled job definitions
README.md           # what this deployment is, who owns it, where the output goes
```

What does **not** go in it: any file from `quorom/`, `migrations/`, `tests/` or
`docs/`. Those are read from upstream. If you find yourself copying one in to
change a line, stop and re-read section 1.

Record in your README which upstream commit or tag you are running. When you
update, that is the thing you move.

---

## 5. Step 2 — The Claude project

Create a project in Claude. Give it these instructions — this is the text that
makes an agent in the project useful rather than guessing:

```
This project runs a Quorom deployment for <YOUR COMPANY>.

The code is upstream at github.com/saaswise-cc/quorom and is read-only to us.
We never edit it, fork it or patch it. Read it there when you need to know how
something behaves. Start with docs/setup.md, then README.md and
docs/supported-configuration.md.

Our repository is <YOUR REPO URL>. It holds only: configuration, references to
secrets, and our deployment pipeline. If a task seems to need a code change,
say so and stop — that is an upstream change, not something we make here.

Our deployment:
- Database: <where>
- Meeting source: Gong
- CRM: Salesforce
- Weekly output lands: <where>

House rules for this project:
- Every number names its source, or says unknown.
- Prefer measuring to reasoning — go and get the number.
- Never present a guess as a fact. Gaps are output, not failure.
- Do not add columns, scores or features that were not asked for.
```

Add the Linear MCP if your team uses it, so the agent can read the project
below. Nothing in the pipeline requires it.

---

## 6. Step 3 — The Linear project

Create a project for the deployment. It is where the two questions this guide
cannot answer for you get tracked and closed:

- **What runs the scheduled job** (section 12).
- **Where the finished file lands** (section 13). This one decides whether
  anyone reads the output at all.

---

## 7. Step 4 — Salesforce access

Do this before step 7, not after. `quorom init` resolves your CRM field map by
describing your org, and it can only do that if it can reach Salesforce. Run
`init` with Salesforce unconfigured and you get an account with no field map;
a later weekly run with Salesforce *configured* and no map stops rather than
running — because every query would silently fall back to standard fields only
and the output would be quietly wrong. (`quorom resolve-fields` fixes it, but
it is easier not to get there.)

Two ways in.

| Mode | Variables | Use |
|---|---|---|
| **Client credentials** | `SF_TOKEN_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET` | The deployed run. No paste, no expiry. This is what a scheduled job needs. |
| **Pasted token** | `SF_ACCESS_TOKEN`, `SF_INSTANCE_URL` | Trying it out by hand. Expires in about two hours. |

Client credentials come from a Connected App (or External Client App) that a
Salesforce admin at your company creates. Until that exists there is no
unattended weekly run.

> **The one that catches people.** The code prefers a pasted token whenever it
> finds one. A stale `SF_ACCESS_TOKEN` left in your environment silently keeps
> the two-hour path in use even after the client-credentials variables are set —
> and the failure surfaces as a wall of 401s well into a run, not at the start.
> Leave `SF_ACCESS_TOKEN` and `SF_INSTANCE_URL` empty for a deployed run.

The pasted-token runbook is in `docs/salesforce-access.md`.

No managed package is required, and no permission beyond read access to
`Account` and `Contact` plus the ability to describe both objects.

---

## 8. Step 5 — The code and the database

On the machine that will run the pipeline:

```bash
git clone https://github.com/saaswise-cc/quorom.git
cd quorom
python3.12 -m venv .venv && source .venv/bin/activate   # any 3.11+ will do
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

**Name the interpreter, and upgrade pip inside the venv.** Both lines are load-
bearing on a stock Mac. `python3` there is 3.9 — section 3 had you check exactly
that — and a 3.9 venv carries pip 21.2.4, which predates the standard this
project's editable install needs. The failure does not mention Python or pip; it
says `File "setup.py" or "setup.cfg" not found`, which sends you looking for a
missing file that is not supposed to exist. Upgrading pip first is what turns
that into a working install or an honest "requires a different Python" message.

**Why `.[dev]` and not `.`** — `python-dotenv` lives in the `dev` extra, and it
is what reads the `.env` file you are about to write in section 9. Install with
a bare `pip install -e .` and there is no `.env` support at all: the file is
read by nothing, and the first symptom is section 10 reporting `DATABASE_URL`
and `ACCOUNT_DOMAIN` missing while both sit correctly in the file. A deployed
run is the case that genuinely wants the bare install — it takes its values
from your environment's secret store and never has a `.env` to read.

That gives you the `quorom` command. Check it:

```bash
quorom --help
```

Create an empty database and apply the four migrations, **in filename order**:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_core.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0002_identity.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0003_focus_profile.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0004_crm_field_map.sql
```

They create empty tables and nothing else. `ON_ERROR_STOP=1` matters: without
it `psql` carries on past a failed statement and leaves you a half-applied
schema that looks fine.

Verify:

```bash
psql "$DATABASE_URL" -c "\dt"
```

You should see eight tables: `accounts`, `meetings`, `attendees`, `people`,
`person_identifiers`, `person_attendees`, `user_focus_profiles`,
`crm_field_maps`.

Migrations are append-only once applied — your database is yours, not ours, and
cannot be rebuilt from scratch to accommodate an edit.

### Checking the install

The test suite is the one way to confirm the code works on your machine before
you point it at live systems. It needs the `dev` extra, which you installed
above:

```bash
pytest
```

That gives **137 passed, 21 skipped**, and the skips matter: those 21 are the
tests that need a real PostgreSQL, and they skip silently when they cannot find
one. A run that skips them is green on any machine with no database, which is to
say green almost everywhere, including where something is genuinely broken. To
run all 158, point `QUOROM_TEST_DSN` at a Postgres and run it again:

```bash
export QUOROM_TEST_DSN=postgresql://postgres@localhost:5432/postgres
pytest
```

Expect **158 passed**. Anything else is worth stopping for.

> **Not your product database.** The suite creates and drops its own databases
> on whatever server that DSN names. Give it a scratch Postgres — a container is
> ideal — never the deployment you set up above.

---

## 9. Step 6 — Configuration

Copy `.env.example` to `.env` and fill it in. `.env` is git-ignored. In a
deployed run these values come from your environment's secret store instead —
same names, no file.

The four that a run cannot start without:

```bash
DATABASE_URL=postgresql://user:password@host:5432/quorom
ACCOUNT_DOMAIN=acme.com          # your own primary domain; names the account row
GONG_ACCESS_KEY=
GONG_ACCESS_KEY_SECRET=
```

Then Salesforce per section 7, and `HUBSPOT_SERVICE_KEY` if you have one.

Everything else has a default and can be left alone until you have seen an
output and want to change something:

| Variable | Default | What it does |
|---|---|---|
| `RECENT_DAYS` | 90 | How far back still counts as recent contact — **and** how far back `quorom import` reaches with no dates given. One number deliberately: importing less than the recency window puts "no" next to people you met inside it. |
| `SHORTLIST_SIZE` | 3 | People per company on the stakeholder list. The cap is a feature. |
| `GROUP_CALL_MIN` | 8 | Above this many external attendees, a meeting is labelled a group call on the row — so a training webinar does not read as a relationship. |
| `WEEK_START` | current week | Monday of the target week, `YYYY-MM-DD`. |
| `TZ_OFFSET` | `-04` | The offset the week boundaries are cut on. |
| `OUTPUT_DIR` | `output` | Where the three files land. |
| `CUSTOMER_ACCOUNT_TYPES` | empty | Substrings of `Account.Type` marking an existing customer. Empty means the gate is off and ICP fit is employee band plus HQ geography only. Leave it off unless your `Type` field is genuinely maintained as a lifecycle field. |

> **`python-dotenv` does not override an exported variable.** If you export
> something in your shell, that one wins over `.env`. Verify which one the
> process actually sees rather than assuming.

---

## 10. Step 7 — Initialise

Two rows have to exist before anything works: your account, and an active focus
profile. `quorom init` creates both, and resolves the CRM field map while it is
there.

```bash
quorom init \
  --internal-domains acme.com,acme.io \
  --employee-min 200 --employee-max 10000 \
  --geographies "North America" \
  --seniority c-level,vp,director
```

**`--internal-domains`** — your own email domains, and how a colleague is told
from someone at the other company. Give the part after the `@`. Get this wrong
and every one of your own people appears as an external attendee, every week.

**`--employee-min` / `--employee-max`** — the ICP employee band. A company with
no employee count in your CRM fails the test with "no size" rather than passing
on the benefit of the doubt.

**`--geographies`** — HQ geography. A bare value is a region: `North America`,
`EMEA`, `APAC`. Prefix with `country:` to name one country —
`--geographies "North America,country:Germany"`. Common aliases resolve, so
`United States`, `USA` and `US` are the same place. A region or country the
pipeline does not recognise is **refused here**, not warned about — it used to
be accepted, apply no geography filter at all, and report every company met as a
fit.

**`--seniority`** — the bar a CRM title has to clear to reach the stakeholder
list. Known levels: `c-level`, `cxo`, `cro`, `vp`, `director`, `founder`,
`manager`. An unrecognised level is matched against the title verbatim, so a
typo matches nobody and every company's bench comes back empty. `init` warns
about that rather than letting you find it in an artifact.

What you should see, **with Salesforce configured**: three `[✓]` lines — the
account, the focus profile, and the field map with the fields it resolved and
the percentage of records populating each. Read that third block. It is the only
place you will see which field the pipeline decided means "employee count" in
your org, and whether that was right.

**Without Salesforce configured** you get two `[✓]` and one `[i]`, and that is a
successful run, not a failed one:

```
[✓] Account acme.com created · internal domains: acme.com, acme.io
[✓] Focus profile v1 created · 200-10000 employees · NA · c-level, vp, director
[i] Salesforce not configured — no field map resolved.
[*] Next: quorom import
```

The `[i]` is the third block telling you it had nothing to resolve against. The
account and the profile are written and `quorom import` will run. What you do
not have is a field map, and section 7 is the reason to care: configure
Salesforce later and the weekly run will stop until you have run
`quorom resolve-fields`.

**Re-running it** with the same arguments writes nothing. With a *different*
profile it refuses: the profile decides which companies appear on the map, so
changing it is `--replace`, which supersedes the active version and keeps the
old one, inactive, so last week's output stays explicable. Adding a domain later
needs no `--replace` — same profile arguments, one more domain.

---

## 11. Step 8 — Import your history

```bash
quorom import
```

With no arguments this imports the last `RECENT_DAYS` days. It prints how many
calls it found and how long it took — those two numbers are what you extrapolate
a longer backfill from.

For real history, extend the range:

```bash
quorom import --from 2025-10-01 --to 2026-08-24
```

Import at least `RECENT_DAYS` of history before your first weekly run. That
setting decides whether the "Recent contact?" column says yes or no; importing
less produces rows saying "no" for people you actually met.

**Re-importing is safe.** Every write is guarded, and a test asserts that
running the same range twice leaves every table count unchanged. A backfill and
an overnight run *will* overlap, and that is fine.

---

## 12. Step 9 — The first weekly run

```bash
quorom weekly
```

Or for a specific week:

```bash
WEEK_START=2026-08-17 quorom weekly
```

It writes three files into `OUTPUT_DIR` and nothing anywhere else — no writes
back to Gong, Salesforce, HubSpot or anywhere in your CRM:

- `weekly_stakeholder_map_<week>.xlsx` — the artifact, four tabs
- `stakeholder_inputs_<week>.json` — every input the run read
- `weekly_view_<week>.html` — a single-page view of the same thing

The four tabs:

| Tab | What it answers |
|---|---|
| **1 — Met this week** | Who attended from outside, one row per person, with their CRM title, LinkedIn and whether a mobile number is on file |
| **2 — Missing from CRM** | Which of those people are not in Salesforce or HubSpot. Attendees with neither email nor domain (meeting bots) are listed at the foot — suppressed visibly, not dropped. |
| **3 — Company coverage** | Every external company met: size, HQ, whether it meets your profile, how many contacts you hold |
| **4 — Stakeholder list** | The map. The senior people at the ICP-fit companies worth considering, capped at `SHORTLIST_SIZE` each |

**Things in the output that are deliberate, not defects.** Read
`docs/supported-configuration.md` before concluding anything is broken:

- A company with no employee count is **excluded**, not given the benefit of the
  doubt.
- `HQ unknown` and `HQ not in region` are different rows. One is missing data,
  the other is a decision your profile made.
- A company with no senior CRM contact gets an explicit
  `— no senior contact in Salesforce —` row rather than being left out.
- Mobile numbers are reported as present or absent, never revealed or stored.
- **No action is suggested per person.** The output says who is worth
  considering and stops. Outreach is a sequence — connect, perhaps message,
  perhaps request a meeting — and that sequence is not decided here.
- **Nobody is checked for still being at the company.** CRM contacts go stale.
  The column is absent rather than saying "not checked" on every row.

---

## 13. Step 10 — Schedule it

**This repository defines no packaging and no scheduling.** That is deliberate:
what runs a scheduled job is different in every environment, and guessing yours
would be worse than saying so.

Two jobs:

| Job | Command | When |
|---|---|---|
| Overnight import | `quorom import --yesterday` | Daily, after your calls have finished syncing to Gong |
| Weekly run | `quorom weekly` | Weekly, after the last import of the week |

What the runner needs: the repository at a known commit, the Python environment,
the environment variables from your secret store, outbound network to
`api.gong.io` and your CRM, and network to your database.

Look first at whatever already runs alongside your database — if that platform
offers scheduled tasks, it is the shortest path and the credentials are already
near it.

**A failed run does not currently retry.** Connection errors are not retried,
deliberately: what should happen when a run fails is a decision about your
schedule, not about the code. Decide it when you decide the runner, and make
sure a failure is visible to a person.

---

## 14. Step 11 — Where the file lands

Decide this before you turn the schedule on, and write it down in your Linear
project.

An `.xlsx` in an output directory on a server is not a delivery. Somebody has to
receive it — a person, a channel, a shared drive. This is the step that decides
whether the map gets read, and it is the one most likely to be left until later
and then never done.

---

## 15. When it goes wrong

| What you see | What it is |
|---|---|
| `[!] Missing environment: DATABASE_URL, ACCOUNT_DOMAIN` | **Check first: are they set in a `.env`, and did you install with `pip install -e .` rather than `pip install -e '.[dev]'`?** Without the extra, `python-dotenv` is absent and the whole file is ignored, so correctly-set values are reported missing. `quorom` now warns about this on stderr when a `.env` is present. Otherwise: those two are required before anything runs, and an exported shell variable beats the file. |
| `[!] The schema is not there. Apply the migrations first` | Section 8. |
| `ERROR: File "setup.py" or "setup.cfg" not found. Directory cannot be installed in editable mode` (with `(A "pyproject.toml" file was found, but editable mode currently requires a setuptools-based build.)`) | Your `pip` is too old for an editable install, which almost always means the venv was built by a too-old Python. Nothing is missing from the repository — there is deliberately no `setup.py`. `python -m pip --version` and `python -V` inside the venv; if Python is below 3.11, rebuild the venv with an explicit `python3.12 -m venv .venv`. Section 8. |
| `[!] No account named '<x>'. Run 'quorom init' first.` | `ACCOUNT_DOMAIN` does not match any account row — either you skipped `init`, or the value changed since. |
| `accounts.internal_domains is empty` | `init` did not run, or ran without `--internal-domains`. Every attendee would be classified external. |
| A run stops before doing anything, complaining about the focus profile | There is no active profile. This is a hard error on purpose: an absent profile makes the ICP test pass everything, and the output would look entirely normal and be wrong. |
| A run stops complaining about the field map | Salesforce is configured but no map is stored. `quorom resolve-fields`. |
| `[!] Gong credentials not configured` | `GONG_ACCESS_KEY` / `GONG_ACCESS_KEY_SECRET`. |
| A wall of `401`s partway through a run | An expired pasted Salesforce token. It means "connected, token expired", not a network problem. Section 7 — and check whether an exported shell variable is winning over your `.env`. |
| A column reads `not available in this CRM` | The field map resolved nothing for it. Expected, not a failure. `quorom resolve-fields` after your admin adds a field. |
| The employee-count or LinkedIn field looks like it picked the wrong one | Re-read the field-map block from `init`, or run `quorom resolve-fields`, which prints every candidate with its populated percentage and every rejection with the rule that rejected it. Counting tells you which field has data, not which field means what you want. |

**Never print a credential.** A failing test that constructs a real config will
load your environment. Build test clients from stubs.

---

## 16. Keeping up to date

Upstream moves. You take updates by moving to a newer upstream commit or tag —
`git pull`, or whatever your pipeline does to fetch the code — and re-running
any new migrations. Nothing else, because nothing else is yours.

If a new migration is added it will be `0005_` or later; apply the ones you have
not applied, in filename order.

Re-run `quorom resolve-fields` when your Salesforce admin adds a field, installs
or removes a package, or when a column in the artifact stops looking right. The
superseded version is kept, inactive, so what last week's output read stays
answerable.

---

## What this does not support

`docs/supported-configuration.md` is the honest answer to "will this work for
me". Read it before you conclude something is missing — in particular: Gong is
the only meeting source implemented, Salesforce is the only CRM, geography does
not go below country level, and no enrichment provider is wired up.
