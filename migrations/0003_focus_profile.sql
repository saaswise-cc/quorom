-- Quorom v1 — 0003_focus_profile: the per-account ICP configuration
--
-- The focus profile drives the whole product: it decides which companies are
-- ICP fits (employee band + HQ geography) and which titles clear the seniority
-- bar for the stakeholder list. In the M2 spike it is read from v0's shared
-- hosted database as a shortcut. Here it lives in the customer's own database,
-- read over the same connection as the meeting data — which is what makes that
-- a connection-string change rather than a code change.
--
-- This is the per-account ICP config, NOT v0's per-contact focus *scoring*
-- feature. Scoring is out of scope; the profile is core.
--
-- Provenance: v0 `20260413000000_user_focus_profiles.sql` (shape),
-- `m2-weekly/weekly_stakeholder_map.py` load_focus_profile() + meets_profile()
-- + seniority_terms() (read surface).
--
-- Departure from v0: the profile is scoped to the ACCOUNT, not to a user.
-- v0 keyed it on `user_id` with a unique-active index per user and RLS policies
-- on `auth.uid()`. v1 has no hosted auth and no `users` table, and the pipeline
-- already selects on (account, is_active, max version) without reference to a
-- user — so the user column would be a foreign key to nothing, guarding a
-- distinction the read path never makes. On the org this was measured against
-- there is exactly one profile row, so nothing is lost in the migration.

create table user_focus_profiles (
  id             uuid primary key default gen_random_uuid(),
  account_id     uuid not null references accounts(id) on delete cascade,

  -- Versioned rather than updated in place: a profile change alters which
  -- companies appear on the map, so the run that produced a given artifact
  -- needs to stay reconstructable.
  version_number integer     not null default 1,
  is_active      boolean     not null default true,

  -- Read by the pipeline as:
  --   employee_count_min / employee_count_max  -> the ICP employee band
  --   hq_geographies                           -> the HQ geography test
  --   focus_seniority                          -> the Salesforce Title LIKE clause
  --                                               behind the senior CRM bench
  -- Left as jsonb: the profile's shape is customer configuration, and pinning it
  -- into columns would put per-customer differentiation in the schema.
  profile_data   jsonb       not null,

  note           text,
  created_at     timestamptz not null default now(),

  unique (account_id, version_number)
);

-- The pipeline reads the active profile for an account. One active row at a
-- time, enforced rather than assumed — two would make the run's ICP filter
-- depend on row order.
create unique index user_focus_profiles_one_active
  on user_focus_profiles (account_id)
  where is_active;

-- The table keeps v0's name so the migration is a straight copy and the
-- pipeline's existing query is unchanged. It is account-scoped despite the
-- 'user_' prefix; renaming it is a cosmetic change that can happen once the
-- data load is done, not during it.
