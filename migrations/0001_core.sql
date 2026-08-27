-- Quorom v1 — 0001_core: accounts, meetings, attendees
--
-- Designed backwards from what the pipeline reads, not forwards from v0's
-- schema. Every column below is either read by a column of the stakeholder-map
-- artifact or written by the Gong importer that produces it. Anything in v0
-- that neither reads nor writes was left out; a later migration adds a column
-- when a read path needs it.
--
-- Provenance for the shape: v0 `migrations/20260330000000_core_schema.sql`
-- (tables), `src/lib/gong/process-gong-import.ts` (write surface),
-- `m2-weekly/weekly_stakeholder_map.py` MEETINGS_SQL + MET_HISTORY_SQL (read surface).
--
-- Deliberate departures from v0, each with a reason:
--
--   * No RLS, no `auth.uid()`, no `current_account_id()`. v0's policies bind the
--     schema to its hosting platform's auth schema. v1 deploys single-tenant
--     inside the customer's environment with account-scoped keys read from the
--     environment, so row-level isolation has no user to key off and would not
--     run on a plain Postgres.
--
--   * No credential columns. v0 `accounts` carried zoom/google/salesforce OAuth
--     tokens, an enrichment-provider API key and `stripe_customer_id`; v0 also
--     stored per-account Gong keys (`configure_gong`). The README's rule is that
--     secrets are read from the environment and never committed — so Gong,
--     Salesforce, HubSpot and provider credentials are env config in v1, not rows.
--
--   * `provider` and `domain_kind` are text + CHECK, not enums. v0 needed three
--     separate `alter type ... add value` migrations to add gong/teams/other, and
--     the pipeline casts `a.domain_kind::text` on every read to get around the
--     enum. A CHECK constraint extends with a plain ALTER and drops the cast.
--
--   * `accounts` keeps its id and the account_id foreign keys even though a
--     single-tenant deploy has exactly one row. Keeping the column is what lets
--     the same schema and the same queries ship to every customer — differentiation
--     by config, never code.

create table accounts (
  id               uuid primary key default gen_random_uuid(),
  -- Matched by name against the ACCOUNT_DOMAIN env value ('acme.com').
  -- Read by: every query in the pipeline, as the account scope.
  name             text        not null unique,
  -- Read by: the Gong importer, to classify an attendee domain as internal
  -- vs external. `attendees.domain_kind` is derived from it at import time.
  internal_domains text[]      not null default '{}',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table meetings (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references accounts(id) on delete cascade,

  -- Written by: the importer. 'gong' is the only value the pilot produces;
  -- the others are carried so a second source does not need a migration.
  provider    text not null
                check (provider in ('gong', 'zoom', 'google_meet', 'teams', 'other')),
  -- The provider's own call id. With account_id and provider it is what makes
  -- the importer's upsert idempotent, so a re-run of an overlapping date range
  -- does not duplicate meetings.
  provider_id text not null,

  -- Read by: MEETINGS_SQL (the meeting titles aggregated per person on tab 1).
  title       text,
  -- Read by: MEETINGS_SQL (the week window) and MET_HISTORY_SQL
  -- (first_met / last_met, and the recency test behind 'Recent contact?').
  start_time  timestamptz,

  -- Written by the importer, read by nothing yet. Kept because they arrive free
  -- in the same upsert and dropping them would mean re-importing to get them
  -- back; called out here so they are not mistaken for a live read path.
  end_time         timestamptz,
  duration_seconds integer,

  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  unique (account_id, provider, provider_id)
);

-- MEETINGS_SQL filters one week by start_time within an account; MET_HISTORY_SQL
-- scans all of an account's meetings (1,942 rows on one real org).
create index meetings_account_start_idx on meetings (account_id, start_time);

create table attendees (
  id           uuid primary key default gen_random_uuid(),
  meeting_id   uuid not null references meetings(id) on delete cascade,
  account_id   uuid not null references accounts(id) on delete cascade,

  -- Read by: 'Name' on tabs 1 and 2, and the name-only gap rows. Nullable on
  -- purpose — an attendee with no name is a gap to report, not a row to drop.
  name         text,
  -- Read by: every reconciliation lookup (Salesforce and HubSpot are both
  -- queried by email) and the join key of MET_HISTORY_SQL. Lowercased at read
  -- time by the pipeline, not stored normalised.
  email        text,
  -- Read by: company grouping (tab 3 and tab 4 are keyed on domain) and the
  -- Salesforce/HubSpot domain queries.
  domain       text,
  -- Read by: the external-attendee filter that both SQL queries open with.
  -- Derived at import from accounts.internal_domains.
  domain_kind  text
                 check (domain_kind in ('internal', 'external', 'personal')),

  -- Written by the importer as the Gong party id; the importer also uses it to
  -- tell a re-import of the same call from a new attendee.
  provider     text not null
                 check (provider in ('gong', 'zoom', 'google_meet', 'teams', 'other')),
  provider_uid text,

  created_at   timestamptz not null default now()
);

-- Both queries filter external attendees within an account before anything else.
create index attendees_account_kind_idx on attendees (account_id, domain_kind);
-- MET_HISTORY_SQL groups by (domain, email) across all of an account's history.
create index attendees_account_domain_idx on attendees (account_id, domain);
create index attendees_meeting_idx        on attendees (meeting_id);
create index attendees_email_idx          on attendees (account_id, lower(email));
