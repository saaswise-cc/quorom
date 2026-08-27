# Quorom

Post-meeting stakeholder maps for company-to-company engagement.

**Setting it up: [`docs/setup.md`](docs/setup.md).** Start there. This file is
why the product is shaped the way it is; the setup guide is how you run it.

---

## What this does

Take recorded meetings, identify who actually attended from a target company,
check whether those people exist in the CRM and are attached to the right
company record, then identify the other stakeholders at that company who should
be part of a collective engagement.

**The output is a stakeholder map for one target company at a time**, produced
weekly, as a spreadsheet.

Without this exercise, company-to-company engagement doesn't start at all. That
is the value proposition — not better insight, not richer briefs. Coverage, and
a list of names worth considering.

### Out of scope

Briefs. Deliverables. Focus scoring. Outbound sequencing. Transcript moments.
Any web UI. Writing back to any CRM.

The read surface is one file. It is deliberately one file.

---

## The engagement model is asymmetric

This is the part most likely to be read wrong.

It is **not** counterpart-to-counterpart matching. There are two different
actions with two different rules:

**Tier 1 — LinkedIn connection.** Broad, low cost, many-to-many. Any senior
person on your side can reasonably connect with several people at the target
company. A CEO connecting with their VP Product, Head of RevOps and CRO is all
fine. Not seniority-constrained.

**Tier 2 — Meeting request.** Narrow, high cost, seniority-matched. Only pursue
meetings with genuine counterparts — a CEO asks their CEO or CRO, not their
Director of RevOps. One or two names per person on your side.

### These are two kinds of engagement, not two labels to stamp on people

The asymmetry governs *who is worth approaching at all*. What does not follow is
that each person gets one action stamped on them. Real outreach is a sequence,
not a branch: it starts with a LinkedIn connection if one isn't already in
place, may become a message, and may or may not become a meeting request. A
column asserting *connect* or *request meeting* per row is wrong at the first
step, and it asserts a decision — the outreach sequence — that hasn't been made.

So the output distinguishes the two by **who it puts in front of you and how
senior they are**, not by printing an instruction beside each name. It says who
is worth considering and stops.

This was built the other way first, and it did not survive contact with a real
list.

---

## Design principles

**Gaps are output, not failure.** Companies, people and titles will sometimes be
wrong. That is expected. Hiding it is not acceptable.

**Provenance on every field.** Every value records where it came from — the CRM,
a provider, a meeting attendee record, or manual research. Someone correcting
this map needs to know what to trust.

Provenance carries precedence. Manually verified values outrank everything and
are never overwritten by an automated run. A person who did the work by hand
should not have to do it twice.

**Never present a guess as a fact.** Unresolved entries appear as explicit
"not found" rows. They are never silently substituted or dropped.

**Every number names its source, or says unknown.**

**Enrichment costs money.** Project spend before any bulk operation, and default
to the cheapest field that unblocks the action. Today the pipeline calls no
enrichment provider at all and spends nothing.

---

## Differentiation is configuration, never code

Everything specific to a deployment is an account row or an environment value.
Nothing about a particular customer belongs in this repository — which is what
lets one codebase serve everyone without a fork.

Per-deployment configuration covers:

- **Focus profile** — seniority levels and company-scope criteria (employee
  band, HQ geography) that define the stakeholder pool
- **CRM field map** — the resolved API names of every non-standard field the
  pipeline reads (below)
- **Run tuning** — shortlist size, recency window, group-call threshold

### The CRM field map

Standard CRM fields are portable; custom fields are not, and custom fields are
where the useful signal lives. Salesforce has three tiers: **standard** fields
(`Title`, `Email`, `MobilePhone`, `LastActivityDate`, `Account.Type`) present in
every org; **managed-package** fields, present wherever that package is
installed, with the namespace guaranteeing the API name; and **org-local
custom** fields, named by that org's admin and unique to them.

The failure is not graceful. A field that doesn't exist raises `INVALID_FIELD`
and kills the entire query — it does not return an empty column. A hardcoded
custom field name is therefore not a cosmetic portability wart; it is a run that
dies at the next deployment. It is also per-customer differentiation living in
code, which forces a fork — and telling people to edit the field names
themselves is that same fork by another route.

So: **the pipeline never hardcodes a non-standard field name.** At setup it
describes the object, matches fields against generic patterns (`linkedin`,
`employee count`), counts how many records populate each survivor, and writes
the resolved names into the deployment's config row; every query is built from
that map. Unresolved fields degrade their column to an explicit "not available
in this CRM" instead of failing the run. The repository holds only the patterns
and the standard fields.

Two things about it were forced by real data rather than designed in advance,
and both are worth knowing before you read a field-map report:

**It keeps a list per logical field, not a winner.** In one org, three of the
thirty-nine companies met in a single week had an empty country in the
best-populated field and a populated one in the next. A map storing only the
winner would have blanked their HQ and dropped one of them out of the ICP set.

**Population alone picks the wrong field.** In the same org, the best-populated
field matching `/linkedin/` on `Contact` was the *company's* page, beating the
person's profile URL. Counting tells you which field has data, not which field
means what you want. That is why exclusion patterns carry as much weight as
inclusion ones, and why every rejection is stored with the rule that rejected
it — so a wrong match is visible instead of silent.

### Provider rule

**Never silently substitute providers.** When a deployment's configured provider
doesn't resolve someone, that person appears as an explicit "not found in
&lt;provider&gt;" row. Never filled from a different provider. Never dropped.

A gap you can see is actionable. A map that looks complete but isn't is worse
than one with holes in it.

This is non-negotiable where the provider is also the customer: quietly filling
their coverage gaps with a competitor's data, inside a product they are paying
for, is not something that ships. Provenance is visible.

---

## Deployment model

Build once, deploy per customer. This repository is the single source of truth.
Each deployment is single-tenant, inside its own environment, reading its own
systems. No data and no credentials live here or in any Quorom-operated store.

- **Where it runs.** Inside your trust boundary. Your database holds the
  meeting-identity graph; sensitive contact fields — email, phone — pass through
  to your CRM and are never persisted by Quorom. Data residency is solved by
  *where it runs*.
- **Transport is yours.** How the code lands in your environment — your GitLab
  and runners, a GitHub Actions pipeline, a container image in your cloud — is
  per-deployment and stays out of the codebase. Your version control holding a
  copy is fine; your version control being where changes originate is not. That
  is a fork, and a fork can take no update. See `docs/setup.md` §1.
- **Secrets** are read from the environment — a git-ignored `.env` locally, your
  environment's secret store in production. Never committed.

**Pipeline-first.** The read side is a reconciliation pipeline that emits an
artifact. There are no MCP tools and no interactive surface. One is added only
when a real interactive read is demonstrated, not assumed in advance.

---

## Cost discipline

Field costs are provider-dependent; verify against your configured provider
before any bulk operation.

| Field | Typical cost | Scope |
|---|---|---|
| Titles (person already in CRM) | Free | Backfill from the CRM, not a provider |
| Person record — title, LinkedIn URL, current employer | One record charge | These arrive together, not priced separately |
| Company record — firmographics | Higher, per company | Per company, not per person |
| Mobile number | Highest | Shortlist only. Never bulk. |

Before spending on the expensive fields, determine whether availability can be
checked without a paid reveal. If it can't, sample a handful of known names and
report the hit rate before scaling.

**As shipped, none of this applies:** no enrichment provider is wired up and a
run spends nothing. Every field in the output comes from your own systems.

---

## What is here

```
docs/setup.md                   how to stand a deployment up — start here
docs/supported-configuration.md what is and is not supported today
docs/pipeline.md                the six steps, and the read path each serves
docs/salesforce-access.md       the two Salesforce auth modes
migrations/                     the schema, four files, applied in order
quorom/                         the pipeline
tests/                          run with `pytest`
```

---

## Licence

Business Source License 1.1 — see `LICENSE`.

In short: you may use Quorom to produce stakeholder maps for your own
organisation, including deploying it in infrastructure you control. You may not
provide it, or a derivative of it, to third parties as a hosted or managed
service. Four years after each version is first made publicly available, that
version converts to Apache License 2.0.

The BSL is not an Open Source licence. The `LICENSE` file is the terms; the
paragraph above is not.

## Contributions

**Contributions are not accepted.** Pull requests are turned off. Copyright is
sole and undivided, which is what keeps relicensing a decision that can still be
made — a licence can be loosened later, never tightened.

This is not a comment on anyone's code. If you are running Quorom and something
needs to change, say so rather than patching locally: a local patch is a fork,
and a fork can take no update. See `docs/setup.md` §1.
