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

**Yours — a repository in your own version control.** Four things, and nothing
else:

| Yours | What it means |
|---|---|
| Configuration | The values that make this deployment yours — your domains, your ICP, your tuning |
| Secret *references* | The names of the secrets, not the secrets. Values live in your secret store. |
| Your deployment pipeline | How the code reaches a machine, and what runs it on a schedule |
| The record of what it produced | Every weekly run, kept. A run cannot be reproduced later — see section 14. |

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
   read the output. First, so the agent is with you for the rest.
2. **A repository in your own version control** — config, secret references,
   your pipeline, and the record of every run. Per section 1.
3. **A Linear project** — where the work and the open questions are tracked.
4. **A running deployment** — a PostgreSQL database, the pipeline installed
   against it, and a schedule that runs it.

---

## 3. Before you start

### Two machines, and they are not the same question

Most of the "wait, where am I supposed to be running this?" confusion in a
setup like this comes from one place: there are two machines involved, they are
usually different, and they get decided at different times.

| | What it is | Decided |
|---|---|---|
| **The workstation** | Where you install from, apply the migrations from, and run the first `init`, `import` and `weekly` by hand. Your own laptop or desktop if it can reach the systems below; otherwise a jump box, a VM or a server inside your network. | Now — sections 8 to 12 |
| **The runner** | Whatever executes the two scheduled jobs afterwards, unattended, every week without you. A server, a container, a scheduled task on your hosting platform. | Later — section 13 |

Ask them separately, and in that order. Everything through section 12 happens
on the workstation, and nothing before section 13 requires you to have picked a
runner. They can turn out to be the same machine; do not assume it.

### What both of them have to reach

The pipeline talks to three outside systems and needs a network path to all
three:

- your **PostgreSQL database** — frequently private to your own network or to
  your hosting platform's,
- **`api.gong.io`**, over HTTPS,
- your **CRM** — your Salesforce org, plus HubSpot if you use one.

That is what decides which machine the workstation can be. A public API like
Gong is reachable from almost anywhere. A private Postgres and a Salesforce org
behind your company's login usually are not, and typically want a machine
inside your own network. A sandboxed environment in particular — the container
an agentic coding tool runs commands in, a hosted notebook, a cloud shell you
did not configure yourself — will often reach `api.gong.io` perfectly well and
fail on the other two, and it fails as a connection timeout rather than as
anything that says "wrong machine". Run the checks in the table below from the
machine you actually intend to use, before you install anything on it.

### How to run the commands in this guide

Every `bash` block below is typed at a shell prompt on the workstation, unless
the text says otherwise.

- **The application.** On macOS that is **Terminal** — Applications → Utilities
  → Terminal, or ⌘-Space and type "Terminal". This guide has been walked
  end to end on macOS only; other platforms are untested here.
- **The directory.** If you have no convention of your own, use **`~/quorom`**
  — a folder named `quorom` in your home directory. Section 8 creates it by
  cloning into it, and every command after that assumes you are inside it.
  `cd ~/quorom` gets you back there in a new terminal.
- **Angle brackets are deleted, not typed.** Where a command or a template
  contains something like `<paste the connection string here>` or
  `<YOUR REPO URL>`, replace the whole thing — brackets and all — with your own
  value. Nothing catches you if you don't: the shell will cheerfully set a
  variable to the literal words `<paste the connection string here>`, report no
  error, and let you discover it several steps later as a connection failure
  that looks like a bad password.
- **An exported variable dies with the terminal window.** `export FOO=…` lasts
  for that one tab. Close it, open a second one, or restart the machine, and it
  is gone — and the commands that needed it fail in ways that never mention it.
  Section 8 says what to do about the one this guide leans on.

### What you need in hand

Everything below is needed. Get them in hand first; discovering a missing one
halfway through step 7 costs more than checking now. Run the checks from the
workstation.

| You need | Why | How to check |
|---|---|---|
| **PostgreSQL 13 or later**, reachable from both machines | The product database. `gen_random_uuid()` is built in from 13. | `psql "<your connection string>" -c "select version();"` |
| **Python 3.11 or later** on the workstation | The pipeline is Python. | `python3 --version` |
| **`psql`** on the workstation | Four SQL files to run | `psql --version` |
| **Gong API credentials** — an access key and secret, **read-only** | The meeting source. Everything downstream reads meetings imported from here. | Gong admin → API |
| **Outbound network to `api.gong.io`** from both machines | The overnight job needs it too, not just your workstation | `curl -sI https://api.gong.io` |
| **Salesforce access** — see section 7 | The CRM half of the map: reconciliation, firmographics, the senior contact bench | |
| **A HubSpot private-app key** *(optional)* | Marketing contacts. Absent, the HubSpot columns are left out of the output entirely rather than reported as "no" or as a contact count of 0. | |

**What the Gong key needs, and what it must not have.** Read-only, covering
**Calls** — including attendee data, which is the half the whole stakeholder
map is built from — and **Users**. No write scopes: the pipeline never writes
anything back to Gong, so a key that could is a liability with no upside.

> **The Access Key Secret is shown once.** Gong displays it at the moment of
> creation and cannot show it to you again afterwards. There is no "reveal"
> later — if you lose it, you issue a new key. Put it straight into your secret
> store as you create it, not into a note, a message or a chat window
> (section 4).

**Salesforce is effectively required**, though the pipeline runs without it. The
stakeholder list is built entirely from Salesforce contacts, so without it you
get the meeting reconciliation and the company coverage, and a stakeholder tab
that is all gaps.

**It costs nothing to run.** Every field in the output comes from Gong,
Salesforce or HubSpot — data you already own. No enrichment provider is called.

---

## 4. Step 1 — The Claude project

**Do this one first.** Once the project points at this repository, everything
after it is done with an agent that has already read this guide sitting
alongside you — including the steps that are fiddlier than they look. That is
the working arrangement section 2 describes and the rest of this document
assumes.

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
- Never put a credential in this project or in a conversation. Name where a
  secret lives; never its value.
```

> **`<YOUR REPO URL>` does not exist yet, and that is fine.** You create that
> repository in step 2. Leave the placeholder alone for now and fill it in when
> you have the address. Nothing in this step waits on it, and the agent is
> useful without it — the line that matters here is the upstream one. Everything
> else in the template you can fill in immediately.

**Pointing the project at this repository is just the URL.** It is a public
repository on GitHub. There is no connector to authorise, no token to issue, no
integration to install, no permission to grant and no setting to go and find.
The address in the instructions above is the whole mechanism: an agent can read
the code, the migrations and these docs from it directly. If you are hunting for
a configuration screen, stop — there isn't one.

**Do not upload files from this repository into the project as knowledge
documents.** It is a tempting shortcut and it goes wrong quietly. An uploaded
file is a copy, frozen at the moment you uploaded it. The first time upstream
changes, your copy is silently wrong, and from then on everyone in the project
is following a stale document in good faith — with no diff, no warning and no
merge path back. That is the fork problem of section 1 in a different costume:
same drift, same silence, same dead end. The project *references* the
repository; it never *contains* it. When you need the current text of a file,
have the agent read it at the URL.

### Secrets do not go into the conversation

You are about to be handed credentials — a database connection string, a Gong
Access Key Secret, a Salesforce client secret, perhaps a HubSpot key. This is
the rule for all of them, and it is here rather than further down because by
section 7 it would already be too late.

- **Never paste a secret into the chat.** Not a connection string, not a token,
  not a client secret, not an API key, not "just so you can check the format".
  A conversation is stored and searchable; it is not a secret store.
- **Run the commands that touch a credential yourself**, in your own terminal,
  and report back the result rather than the input: "connected", "eight
  tables", "401 on the second call". The agent needs the outcome. It never
  needs the value.
- **A secret shown once goes straight to your secret store** — not into a note,
  not into a message you intend to delete later. Gong's Access Key Secret is
  the case that bites (section 3): displayed at creation, never again.
- **Project instructions and tracker issues name where a secret lives, never
  what it is.** "Database credentials: our secret store, key
  `QUOROM_DATABASE_URL`" is the right shape. Those texts are permanent and
  visible to everyone in the workspace, which is exactly what a credential
  must not be.
- **If one does land somewhere it shouldn't, rotate it.** Deleting the message
  is not a rotation.

The same care applies to output, not just input: a traceback or a log line can
carry a connection string inside it. Read what you are about to paste. Section
15 has the case that catches people — a failing test that builds a real config.

### Reading it and running it are different things

The guide asks you to do both, and they are easy to conflate. They need
completely different things:

| Activity | What it needs |
|---|---|
| **Reading** — how does this behave, what does that flag do, what does `0002` create, why is it shaped this way | The URL. Nothing else. No clone, no credentials, no database. |
| **Executing** — applying the migrations, `quorom init`, `quorom import`, `quorom weekly` | A clone on the workstation of section 3 — a machine that can reach your database, Gong and Salesforce. That is step 5, in section 8. |

Asking an agent what `RECENT_DAYS` does, or what a column on tab 3 means, needs
nothing but the address — no setup, no access, and you can do it right now.
Running the weekly job needs a machine, a database, a virtualenv and real
credentials, and the agent in your Claude project is not on that machine unless
you have put it there yourself.

Add the Linear MCP if your team uses it, so the agent can read the project
below. Nothing in the pipeline requires it.

---

## 5. Step 2 — Your repository

Create an empty repository in your own version control. What goes in it:

```
.env.example        # copied from upstream, filled in with YOUR values —
                    # names and non-secret values only, never a secret
deploy/             # your pipeline: however the code reaches a machine
schedule/           # your scheduled job definitions
runs/               # every weekly run, committed — see section 14
README.md           # what this deployment is, who owns it, where the output goes
```

What does **not** go in it: any file from `quorom/`, `migrations/`, `tests/` or
`docs/`. Those are read from upstream. If you find yourself copying one in to
change a line, stop and re-read section 1.

Record in your README which upstream commit or tag you are running. When you
update, that is the thing you move.

Once it exists, put its address into `<YOUR REPO URL>` in your Claude project
instructions from step 1.

---

## 6. Step 3 — The Linear project

Create a project for the deployment. It is where the two questions this guide
cannot answer for you get tracked and closed:

- **What runs the scheduled job** (section 13).
- **Where the finished file lands, and where every run is kept** (section 14).
  The first decides whether anyone reads the output at all. The second decides
  whether you can ever ask what changed.

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

Client credentials come from an app that a Salesforce admin at your company
creates. Until that exists there is no unattended weekly run.

### What to ask your Salesforce admin for

Ask for it as one request, because it is one:

- **An External Client App** in your Salesforce org, with the **client
  credentials flow** enabled.
- **A dedicated run-as user** for that app — an integration user that exists
  for this and nothing else.
- **Read and describe permission on `Account` and `Contact`** for that user,
  and nothing beyond it. No managed package. No write access. No other object.

That is the entire ask. `SF_CLIENT_ID` and `SF_CLIENT_SECRET` come from the
app; `SF_TOKEN_URL` is your org's OAuth token endpoint.

**The run-as user should not be a person.** Pointing it at somebody's own login
works for testing and will break the schedule. The first time that person
changes their password, loses a permission, has MFA enforced on them or leaves
the company, the weekly run stops — at 3am, attributed to nobody, looking from
the outside like a Salesforce outage. A dedicated integration user is the
difference between a schedule that keeps running and one that quietly stopped
in March.

#### Creating the integration user

> *As observed on a Salesforce org, September 2026.* Same caveat as the section
> below: if what is on your screen disagrees with this, trust the screen.

This is the most error-prone step in the guide, and nearly all of the difficulty
is three things with almost the same name.

**The user licence.** `Salesforce Integration` is an API-only *user* licence —
that user cannot log into the UI at all, which is exactly what you want.
Enterprise editions and above include a small number of them at no extra cost,
so check what you already have before assuming you need to buy one.

**The profile.** `Minimum Access - API Only Integrations` is the matching
profile. Start there and add nothing to it.

**The permission set licence — a different thing with almost the same name.**
The permission set that grants object access needs `Salesforce API Integration`,
which is a *permission set* licence, not the user licence above. Choosing
`--None--` lets you build the permission set successfully and then fails at
**assignment**, with:

```
The user license doesn't allow the permission: Read Account
```

That message sends you looking at object permissions, which are fine. The cause
is a licence field two screens back.

**A permission set's licence cannot be changed after it is created.** It is not
in Edit Properties. If you pick the wrong one, delete the permission set and
build it again.

What the permission set should grant: **Read**, **View All Records** and **View
All Fields** on `Account` and `Contact`, and nothing else. View All Fields
rather than ticking fields one by one, because the field map is resolved
dynamically at setup — which fields it will read cannot be enumerated in
advance.

Four smaller things, each of which costs time:

1. **The username must be globally unique across all of Salesforce, and does not
   have to be a real address.** A suffixed form such as
   `quorom-integration@yourcompany.com.prod` works. The *email* field is
   separate and can be an existing monitored inbox.
2. **Select objects by API name.** The object list is full of similar display
   names; `Account` and `Contact` are unambiguous.
3. **`Run As (Username)` wants the username**, not the display name the picker
   offers you. The display name is rejected.
4. **The assignment screen may arrive empty**, with a message about Salesforce
   Classic. There are two list views both named "All Users", and only one of
   them works.

#### Finding it in the Salesforce UI

> *As observed on a Salesforce org, August 2026.* Salesforce moves this
> interface, and a confidently wrong instruction is worse than none: if what is
> on your screen does not match what is below, trust the screen.

**"Connected App" and "External Client App" are not two names for one thing.**
External Client Apps are the current mechanism. On a current org, Setup → App
Manager offers **New External Client App** and there is no "New Connected App"
button at all. Older orgs may still show Connected Apps, and an existing
Connected App keeps working — but if you are creating one today you are
creating an External Client App, and any instructions written for Connected
Apps will not match what you see.

Three things inside that flow cost real navigation time:

1. **The configuration is split across tabs.** Once the app exists, its
   settings are not one page: **Settings** and **Policies** are separate tabs
   and you need both.
2. **"Enable Client Credentials Flow" appears twice, and only the second one
   counts.** There is a checkbox by that name in the app creation form, under
   the OAuth settings — and another by the same name on the **Policies** tab
   afterwards. Ticking the first does not tick the second. **Only the one on
   Policies activates the flow.** Nothing on screen signals this: the app looks
   configured, and the token request fails.
3. **Run As User is inside a collapsed subsection.** On the Policies tab it
   sits under **OAuth Policies**, which is collapsed by default — not at the
   top level of the page. Expand it and set the user. The flow does not work
   without it.

> **The one that catches people.** The code prefers a pasted token whenever it
> finds one. A stale `SF_ACCESS_TOKEN` left in your environment silently keeps
> the two-hour path in use even after the client-credentials variables are set —
> and the failure surfaces as a wall of 401s well into a run, not at the start.
> Leave `SF_ACCESS_TOKEN` and `SF_INSTANCE_URL` empty for a deployed run.

The pasted-token runbook is in `docs/salesforce-access.md`.

---

## 8. Step 5 — The code and the database

**This is workstation work.** Everything in this section runs in a terminal on
the machine from section 3 — the one with network reach to your database,
`api.gong.io` and Salesforce. The runner that executes the schedule is a
separate decision and comes later, in section 13; you do not need to have
chosen it yet, and nothing here depends on it.

```bash
cd ~
git clone https://github.com/saaswise-cc/quorom.git quorom
cd ~/quorom
python3.12 -m venv .venv && source .venv/bin/activate   # any 3.11+ will do
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

`~/quorom` is the default this guide uses; substitute your own location if you
have one, and read `~/quorom` as "wherever you cloned it" from here on. Note
that `source .venv/bin/activate`, like an `export`, applies to that terminal
window only — a new tab needs it again before `quorom` is on the path.

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

### Create the database

The pipeline wants a database of its own. Making one is two moves: get an admin
connection to your PostgreSQL instance, then `CREATE DATABASE`.

**Find the admin connection string, and tell it apart from an app-scoped one.**
A platform that manages Postgres for you typically shows several connection
strings for the same instance, and they are not interchangeable. Two
distinctions matter:

- **Internal versus public hostname.** Hosting platforms usually offer an
  internal or private hostname that only resolves inside their own network,
  alongside a public or external one. From your workstation the internal one
  does not resolve at all. Use the public one here.
- **Admin versus app-scoped credential.** A string scoped to one existing
  database, often with a user of its own, is not the same as the admin or
  superuser credential for the whole instance. Creating a database needs the
  second.

Then create it:

```bash
export ADMIN_DATABASE_URL="<paste the admin connection string here>"
psql "$ADMIN_DATABASE_URL" -c "CREATE DATABASE quorom;"
```

Delete the angle brackets along with the words inside them (section 3). Run
verbatim, that `export` succeeds, silently sets the variable to the literal
text, and hands you a failure one command later that looks like a broken
database rather than an untouched placeholder.

> **`permission denied to create database`.** This is the common case, not an
> edge case. A connection string handed to you for an existing database
> normally belongs to that database's own user, and that user has no
> cluster-wide right to create databases — there is nothing you can type from
> that connection that fixes it. You need either a superuser credential for the
> instance, or whoever administers it to run the `CREATE DATABASE` and hand
> back a connection string scoped to the new one.

**Why it wants a database to itself.** The four migrations create eight tables
under plain, generic names: `accounts`, `meetings`, `attendees`, `people`,
`person_identifiers`, `person_attendees`, `user_focus_profiles`,
`crm_field_maps`. Point them at a database your business already uses and at
least one of those names is likely already taken. Nothing gets destroyed —
`CREATE TABLE` refuses rather than overwrites — but the migration stops
partway, leaving a half-applied schema and an error whose cause is invisible
unless you already knew which eight names to watch for.

Now set the connection string the rest of this guide uses. This one is
app-scoped: it names the new database, not the instance.

```bash
export DATABASE_URL="postgresql://user:password@host:5432/quorom"
```

> **This lasts until you close the terminal.** Every step below reads
> `DATABASE_URL` — the migrations, `quorom init`, `import`, `weekly`. Open a
> fresh tab tomorrow and it is simply not set, and `psql` quietly falls back to
> a local Unix socket:
> `could not connect to server: No such file or directory ... /tmp/.s.PGSQL.5432`.
> That error names a socket path and never mentions the variable, which sends
> you off to check your database when the problem is your shell. Two ways not
> to lose an afternoon to it: re-run the `export` (and
> `source .venv/bin/activate`) in every new terminal, or put the value in the
> `.env` file of section 9, which `quorom` reads on every run. `psql` does not
> read `.env`, so the migrations below need the export either way.

### If you must share a database: a dedicated schema

A dedicated database is the recommendation, and what the rest of this guide
assumes. If your organisation's convention is one database with a schema per
application, that works too, with no code change: the pipeline emits
unqualified table names, so it uses whatever schema the search path resolves
to.

```sql
CREATE SCHEMA quorom;
```

**Set the search path on the connecting role — never as a connection-string
parameter.** This is the important half, and the reason this is the alternative
rather than the recommendation:

```sql
ALTER ROLE quorom_app SET search_path = quorom;
```

A search path passed in the connection string (`options=-csearch_path=…` and
its variants) fails *silently* when it is absent, misspelled or stripped — and
connection poolers do strip it. The connection still succeeds. The queries
still run. They just run against the default schema, creating or reading the
wrong tables, and nothing anywhere distinguishes that from working. Set on the
role, the path is a property of the credential and travels with every
connection it makes.

Confirm it on the connection you are actually going to use, before you migrate:

```bash
psql "$DATABASE_URL" -c "show search_path;"
```

### Apply the migrations

**In filename order:**

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

Some of them will skip, and the skips matter more than they look: those are the
tests that need a real PostgreSQL, and they skip silently when they cannot find
one. A run that skips them is green on any machine with no database — which is
to say green almost everywhere, including where something is genuinely broken.

To run all of them, point `QUOROM_TEST_DSN` at a Postgres and run it again:

```bash
export QUOROM_TEST_DSN=postgresql://postgres@localhost:5432/postgres
pytest
```

**Zero failed and zero skipped** is the gate. pytest prints both counts on every
run, so you do not need a number from this guide to check it. Any failure, and
any remaining skip, is worth stopping for.

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

## 14. Step 11 — Where the file lands, and where it is kept

Two questions, and they are not the same one. Decide both before you turn the
schedule on, and write both down in your Linear project.

### Who receives it

An `.xlsx` in an output directory on a server is not a delivery. Somebody has to
receive it — a person, a channel, a shared drive. This is the step that decides
whether the map gets read, and it is the one most likely to be left until later
and then never done.

### Where every run is kept

Delivery is not retention: a file sent to a person is not a record you can go
back to.

**A weekly run cannot be reproduced.** Your meetings, attendees and people
accumulate in your database and re-importing is safe, so that part is always
recoverable. The rest of the run is not. Company coverage, the ICP verdicts and
the stakeholder list are computed against your CRM *as it stood that week*, and
none of it is written back to the database. Re-run last week's window a month
from now and you get the same meetings reconciled against a CRM that has since
changed — a new map with an old date on it, not the map you produced.

So a run that is not kept is gone. Keep all three files from every run: the
`.xlsx`, the `.json` and the `.html`.

Keep them somewhere private, durable, versioned, and readable by the agent
working in your Claude project. The repository you created in step 2 (section 5) is the obvious
home — it is already all four of those things, and committing each week gives
you a dated history at no cost.

**Not the directory you cloned this repository into.** `output/` is in the
upstream `.gitignore` deliberately: those files hold real contact data, and that
clone points at a public remote. The record belongs in your own repository,
which is private.

**Why bother.** One run is a snapshot, and answers who you met. A year of runs
is a series, and answers the questions actually worth asking — who is new at
this company, whose title changed, which coverage gap closed, which company went
quiet. None of that can be read from a single file, and none of it can be
recovered later from runs you did not keep.

---

## 15. When it goes wrong

| What you see | What it is |
|---|---|
| `[!] Missing environment: DATABASE_URL, ACCOUNT_DOMAIN` | **Check first: are they set in a `.env`, and did you install with `pip install -e .` rather than `pip install -e '.[dev]'`?** Without the extra, `python-dotenv` is absent and the whole file is ignored, so correctly-set values are reported missing. `quorom` now warns about this on stderr when a `.env` is present. Otherwise: those two are required before anything runs, and an exported shell variable beats the file. |
| `[!] The schema is not there. Apply the migrations first` | Section 8. |
| `bad interpreter: no such file or directory` from `quorom` or `pytest` | A virtualenv hardcodes its own absolute path, so renaming or moving the directory breaks every console script in `.venv/bin`. Delete `.venv` and rebuild it where the directory now lives. |
| `ERROR: File "setup.py" or "setup.cfg" not found. Directory cannot be installed in editable mode` (with `(A "pyproject.toml" file was found, but editable mode currently requires a setuptools-based build.)`) | Your `pip` is too old for an editable install, which almost always means the venv was built by a too-old Python. Nothing is missing from the repository — there is deliberately no `setup.py`. `python -m pip --version` and `python -V` inside the venv; if Python is below 3.11, rebuild the venv with an explicit `python3.12 -m venv .venv`. Section 8. |
| `[!] No account named '<x>'. Run 'quorom init' first.` | `ACCOUNT_DOMAIN` does not match any account row — either you skipped `init`, or the value changed since. |
| `accounts.internal_domains is empty` | `init` did not run, or ran without `--internal-domains`. Every attendee would be classified external. |
| A run stops before doing anything, complaining about the focus profile | There is no active profile. This is a hard error on purpose: an absent profile makes the ICP test pass everything, and the output would look entirely normal and be wrong. |
| A run stops complaining about the field map | Salesforce is configured but no map is stored. `quorom resolve-fields`. |
| `[!] Gong credentials not configured` | `GONG_ACCESS_KEY` / `GONG_ACCESS_KEY_SECRET`. |
| A wall of `401`s partway through a run | An expired pasted Salesforce token. It means "connected, token expired", not a network problem. Section 7 — and check whether an exported shell variable is winning over your `.env`. |
| A column reads `not available in this CRM` | The field map resolved nothing for it. Expected, not a failure. `quorom resolve-fields` after your admin adds a field. |
| The employee-count or LinkedIn field looks like it picked the wrong one | Re-read the field-map block from `init`, or run `quorom resolve-fields`, which prints every candidate with its populated percentage and every rejection with the rule that rejected it. Counting tells you which field has data, not which field means what you want. |

**Never print a credential** — and never paste one into a conversation with an
agent. The full rule is in section 4, which is where you should already have
read it. The trap specific to this section: a failing test that constructs a
real config will load your environment, so a traceback can carry a live secret
in it. Build test clients from stubs, and read a traceback before you paste it
anywhere.

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
