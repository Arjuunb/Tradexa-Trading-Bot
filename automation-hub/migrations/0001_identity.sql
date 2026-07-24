-- 0001_identity.sql — TradeLogX Nexus identity & tenancy foundation (Postgres)
--
-- The production source-of-truth identity layer for the multi-tenant SaaS
-- (DSP Sprint 1). This is a POSTGRES/Supabase migration — it is NOT applied to
-- the local SQLite ledger (which keeps its own forward-only runner in
-- database/store.py and its own TEXT-id / REAL-money conventions). Here we use
-- proper production types: uuid PKs, timestamptz, jsonb, foreign keys, and
-- Row-Level Security ENABLE + FORCE on every tenant-scoped table.
--
-- Isolation model: the app sets a per-request GUC after authentication —
--   SET app.current_tenant = '<tenant-uuid>';
-- and every policy filters on it. current_setting('app.current_tenant', true)
-- returns NULL when unset (the `true` = missing_ok), so an unscoped connection
-- sees NOTHING (default-deny) rather than erroring.
--
-- NOTE on Supabase: the `service_role` key BYPASSES RLS by design. To make RLS
-- actually isolate tenants, the app must connect on a NON-bypassrls role (or a
-- role the policies apply to) AND set app.current_tenant per request. FORCE ROW
-- LEVEL SECURITY additionally applies the policies to the table owner. See
-- migrations/README.md.

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ---------------------------------------------------------------- tenants
create table if not exists tenants (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,          -- stable url-safe id ('__owner__' for the single owner)
  name        text not null,
  is_owner    boolean not null default false,
  created_at  timestamptz not null default now()
);

-- ------------------------------------------------------------------ users
create table if not exists users (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  username      text not null,               -- username OR email (as today)
  email         text,
  password_hash text not null,               -- PBKDF2-HMAC-SHA256 (auth.py)
  salt          text not null,
  role          text not null default 'operator',  -- owner | admin | operator | viewer
  verified      boolean not null default false,
  created_at    timestamptz not null default now(),
  unique (tenant_id, username)
);
create index if not exists idx_users_tenant on users(tenant_id);

-- --------------------------------------------------------------- profiles
create table if not exists profiles (
  user_id      uuid primary key references users(id) on delete cascade,
  tenant_id    uuid not null references tenants(id) on delete cascade,
  display_name text,
  avatar       text,                          -- data URI or URL (matches profile.ts)
  theme        text not null default 'dark',
  language     text not null default 'en',
  updated_at   timestamptz not null default now()
);
create index if not exists idx_profiles_tenant on profiles(tenant_id);

-- --------------------------------------------------------------- sessions
-- Refresh-token store for JWT rotation (Sprint 1 auth lifecycle). The access
-- token stays stateless; only the refresh side is persisted so it can rotate
-- and be revoked. We store a HASH of the refresh token, never the token.
create table if not exists sessions (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  user_id       uuid not null references users(id) on delete cascade,
  refresh_hash  text not null,
  user_agent    text,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  revoked_at    timestamptz
);
create index if not exists idx_sessions_user on sessions(user_id);
create index if not exists idx_sessions_tenant_exp on sessions(tenant_id, expires_at);

-- ---------------------------------------------------------- user_settings
-- Same logical shape as the SQLite/Supabase user_settings today (namespaced
-- JSON blobs), re-keyed by tenant for isolation. jsonb instead of a TEXT blob.
create table if not exists user_settings (
  tenant_id   uuid not null references tenants(id) on delete cascade,
  username    text not null,
  namespace   text not null,
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now(),
  primary key (tenant_id, username, namespace)
);

-- ==================================================================== RLS
-- Every tenant-scoped table: ENABLE + FORCE + a tenant-isolation policy. The
-- tenants table isolates on its own id; the rest on tenant_id. Policy names are
-- unique per-table, so `tenant_isolation` is reused intentionally.

alter table tenants enable row level security;
alter table tenants force  row level security;
create policy tenant_isolation on tenants
  using (id = current_setting('app.current_tenant', true)::uuid)
  with check (id = current_setting('app.current_tenant', true)::uuid);

alter table users enable row level security;
alter table users force  row level security;
create policy tenant_isolation on users
  using (tenant_id = current_setting('app.current_tenant', true)::uuid)
  with check (tenant_id = current_setting('app.current_tenant', true)::uuid);

alter table profiles enable row level security;
alter table profiles force  row level security;
create policy tenant_isolation on profiles
  using (tenant_id = current_setting('app.current_tenant', true)::uuid)
  with check (tenant_id = current_setting('app.current_tenant', true)::uuid);

alter table sessions enable row level security;
alter table sessions force  row level security;
create policy tenant_isolation on sessions
  using (tenant_id = current_setting('app.current_tenant', true)::uuid)
  with check (tenant_id = current_setting('app.current_tenant', true)::uuid);

alter table user_settings enable row level security;
alter table user_settings force  row level security;
create policy tenant_isolation on user_settings
  using (tenant_id = current_setting('app.current_tenant', true)::uuid)
  with check (tenant_id = current_setting('app.current_tenant', true)::uuid);

-- Seed the single owner tenant so the current single-owner app maps onto the
-- schema unchanged (slug '__owner__' == services/tenancy.OWNER_TENANT).
insert into tenants (slug, name, is_owner)
  values ('__owner__', 'Owner', true)
  on conflict (slug) do nothing;
