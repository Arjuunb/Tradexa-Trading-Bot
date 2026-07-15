# Storage durability (audit Phase 1 · H-1, M-6)

## The problem the audit found

Only the **ledger** had a durable (Supabase) backend. The paper account, user
accounts + saved settings, AI trade memory, and the decision/skip history all
live in local SQLite under `DATA_DIR`, which on a cloud host defaults to the
*ephemeral* app directory. So on the free/default deploy, a redeploy silently
wiped accounts and paper balances — the data loss you saw after the crash alert.

## What Phase 1 does about it

It cannot make ephemeral storage durable for free, but it makes the situation
**honest and bounded** so nothing is ever lost *silently*, and gives a one-step
path to full durability.

### 1. Durability is now assessed and surfaced (`services/storage_health.py`)

Three tiers, reported by `GET /ops/storage` and shown on the **Bot Health** page:

| Tier | When | What survives a redeploy |
|---|---|---|
| **disk** | `HUB_DATA_DIR` points at a mounted disk (or local dev) | **Everything** |
| **supabase** | no disk, Supabase configured | Trade history only — account / settings / memory are **wiped** |
| **ephemeral** | no disk, no Supabase | **Nothing** |

`GET /ops/storage` now returns the `tier`, a per-store `at_risk` list, and a
plain-English `warning`, and includes the previously-omitted stores (paper
account, users+settings, trade memory, decisions).

### 2. Loud boot warning

On startup, if storage isn't fully durable, the app prints a `STORAGE
DURABILITY WARNING` banner to stderr (visible in Render logs) and writes a
warning to the ledger. You can never run on disposable storage without knowing.

### 3. Retention pruning (M-6)

The nightly task now caps the append-only tables so a persistent disk never
fills: `bot_logs`, `alerts`, `webhook_events` (ledger), `decisions`, and
`skipped_trades` keep the most recent N rows (`HUB_RETENTION_ROWS`, default
20 000). **Trade rows (positions / paper_trades) and AI trade memory are never
pruned** — they are the permanent record.

## Make it fully durable (recommended for real users)

Two levels:

- **Free — trade history only:** create a Supabase project, run
  `data/ledger_schema.sql`, set `SUPABASE_URL` + `SUPABASE_KEY`. Tier → `supabase`.
- **Full — everything survives:** mount a persistent disk and set `HUB_DATA_DIR`
  to it. In `render.yaml`, uncomment the `disk:` + `HUB_DATA_DIR` blocks and
  change `plan: free` → `plan: starter` (a disk requires a paid instance).
  Tier → `disk`, `at_risk` empty.

Until then the warning + Bot Health tile tell you exactly what's at stake.
