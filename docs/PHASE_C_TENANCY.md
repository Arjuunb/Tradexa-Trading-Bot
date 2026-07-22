# Phase C — Multi-tenancy rollout

*Companion to `docs/SAD.md` §5/§19. Phase C makes the platform multi-tenant. It is **incremental and behaviour-preserving**: the app stays single-owner and fully working while each store is made isolation-ready, then the `HUB_MULTI_USER` flag flips the whole thing on.*

## The seam (Phase C-1 — done)

Everything keys on **one** function so tenancy has a single source of truth:

- `services/tenancy.py`
  - `OWNER_TENANT = "__owner__"` — the stable id for the single owner's data (independent of their username, so a rename never re-homes their trades).
  - `multi_user_enabled()` — reads `HUB_MULTI_USER` (off by default).
  - `resolve_tenant(username)` — single-owner → always `OWNER_TENANT`; multi-user → the username; anonymous → owner (never cross-tenant).
- `app.py::_tenant(request)` — the request-layer accessor (`resolve_tenant(_user(request))`).
- `data/tenant_scope.py::ensure_tenant_column(conn, table)` — idempotent expand-migrate for flat-row tables (adds `tenant_id` default owner, backfills existing rows).
- `/health` reports `tenancy.mode` (`single-owner` | `multi`).

**Invariant:** while `HUB_MULTI_USER` is off, `resolve_tenant` returns the owner for everyone, so tenant-aware stores behave exactly as before. Nothing is observable until the flag flips.

## Two migration patterns

| Store shape | Pattern | Primitive |
|---|---|---|
| **Singleton** (`id=1` row) — e.g. `market_prefs`, `account_state` | Re-key by `tenant_id` (PK); migrate the old row to the owner | done inline (see `watchlist_store._migrate`) |
| **Flat rows** — e.g. `paper_trades`, `positions`, `cycle_reports` | Add a `tenant_id` column (default owner), backfill; filter reads by tenant **only when multi-user is on** | `ensure_tenant_column` |

## Rollout checklist (C-2 …) — risk-tiered

Each store: (1) make schema tenant-aware via the right pattern, (2) thread `tenant=` through its methods (default `OWNER_TENANT`), (3) pass `_tenant(request)` from the router, (4) add reads-are-isolated tests. Do the **money stores last and one at a time.**

- [x] **`watchlist_store` (market prefs)** — singleton → tenant-keyed. *Proven pattern (C-1).*
- [ ] **`user_settings`** (already `(username, namespace)`) — formalize `username` as the tenant key via the seam. Low risk.
- [ ] **`custom_store` / strategy JSON** — add `tenant_id` to each record; scope list/get/save. Low risk.
- [ ] **`account_store`** (paper account singleton) — re-key by tenant; **each tenant gets their own paper account.** Medium (money).
- [ ] **Ledger** (`paper_trades`, `positions`, `webhook_events`, `bot_logs`, `alerts`) — `ensure_tenant_column` + tenant-filtered reads. **High (money) — do individually, verify no cross-tenant read.**
- [ ] **`cycle_store`, `decision_store`, `skipped_store`** — `ensure_tenant_column` + filter. Medium.
- [ ] **`trade_memory`, `journal`** — `ensure_tenant_column` (+ FTS scope). Medium.
- [ ] **Grid state** (`grid_store`) — per-tenant snapshot key. Medium.

## Beyond data isolation (C-3 / Phase E)

Data isolation is necessary but **not sufficient** for real multi-user — these must land before flipping `HUB_MULTI_USER` on in production:

1. **Accounts & auth** — relax the single-owner signup lock; real per-user accounts + roles (the `users` table already has `role`); unify with Supabase identity (see Phase B / SAD §10).
2. **Per-tenant engine** — today one in-process engine loop runs one config. Multi-user needs **per-tenant engine loops** (queue-driven workers, SAD §11) so users don't share one engine/paper account. **This is the real blocker** — until it lands, two "users" would share the single engine.
3. **Postgres + RLS** — move the ledger/settings to Postgres (already supported via `SupabaseLedger`) and enforce isolation at the database with Row-Level Security, so a query bug can't cross tenants.

## Flip criteria (do NOT set `HUB_MULTI_USER=1` until all true)

- [ ] Every store above is tenant-scoped **and** its reads filter by tenant.
- [ ] Per-tenant engine/paper-account exists (no shared engine).
- [ ] Postgres + RLS enforcing isolation at the DB layer.
- [ ] Auth issues real per-user identity (not the single owner cookie).
- [ ] Isolation tests: user A can never read/write user B's trades, settings, or engine.

Until then the flag stays off and the platform remains a safe, working single-owner product.
