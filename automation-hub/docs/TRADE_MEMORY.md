# Trading Memory System

Tradexa's **permanent long-term memory of every trade**. Every closed trade is
composed into a rich, 8-category record and remembered **forever unless
explicitly deleted**. The memory powers full-text + similarity search, natural-
language questions, nightly pattern recognition, and data-driven coaching.

Everything here is built from **real captured data** — the decision journal, the
unified decision object, and the ledger. Fields the bot never measured are
stored as honest markers (`not captured` / `Not checked`), never invented. It is
a record + coaching surface only: **it never enables live trading.**

---

## What is remembered (8 categories)

For every trade, `services/trade_memory.compose_memory()` builds:

| # | Category | Source | Honest gaps |
|---|----------|--------|-------------|
| 1 | **Trade Information** | journal row | fees = `0.00 (paper — fees not modeled)`; risk % only if equity known |
| 2 | **Market Context** | brain snapshot | funding rate / Fear & Greed / BTC dominance / support / resistance → `not captured` (no live provider wired) |
| 3 | **Technical Analysis** | brain snapshot + entry checklist | EMA/RSI are real; MACD/VWAP/Bollinger/order-blocks/FVG/BOS/CHoCH → `Not checked` unless the strategy actually computed them |
| 4 | **Strategy** | journal + decision | name, timeframe, setup grade, confidence, brain score, regime |
| 5 | **Execution** | decision + checklist | why opened / why closed, conditions passed / failed |
| 6 | **Emotion & Journal** | manual | your own note (e.g. "FOMO", "entered early") via PATCH |
| 7 | **Trade Outcome** | journal review | result, profit/loss, RR, mistakes, lessons, improvement notes |
| 8 | **AI Reflection** | review + evolution | 4 questions (went well / went wrong / repeat / never again), each traced to a real field — no invented insight |

## Storage — "remember forever unless deleted"

- **Primary:** SQLite at `HUB_TRADE_MEMORY_DB` (default `HUB_DATA_DIR/trade_memory.db`).
  Set `HUB_DATA_DIR` to a persistent mount (or use the free Supabase option, see
  `FREE_PERSISTENCE.md`) so the memory survives restarts/redeploys.
- **Tables:** `trade_memories` (one row per trade + the 8 categories as JSON),
  `memory_reviews` (persisted nightly/weekly/monthly/yearly reviews), and an
  FTS5 index `trade_memories_fts` for full-text search (falls back to `LIKE` if
  FTS5 is unavailable in the build).
- **Postgres mirror:** DDL is appended to `data/ledger_schema.sql` for a durable
  Supabase/Postgres copy.
- A memory is only ever removed by an explicit `DELETE /trade-memory/{id}`.
  Re-closing / re-composing the same trade is idempotent (no duplicates).

## Search & natural-language queries

`GET /trade-memory/ask?q=...` routes a question to a deterministic analytic when
the intent is recognised, otherwise to full-text search:

- "show all losing BTC trades" → result/symbol filter
- "what was my best trade this year?" → top winner by PnL
- "which setup has the highest expectancy?" → ranked by strategy expectancy
- "why am I losing on Mondays?" → weekday breakdown (sample-flagged)
- "repeated mistakes" → the mistake library
- anything else → FTS over reasons / lessons / reflection / notes

`GET /trade-memory/similar/{id}` ranks trades by **cosine similarity** over a
numeric feature vector (side, RR, confidence, brain score, RSI, ATR%, …).

> **Honesty note:** this is local retrieval — full-text (FTS5) + feature-vector
> cosine — **not** an LLM embedding model. The store interface leaves room to
> plug a real embedding backend in later without changing the API.

## Pattern recognition & coaching

`services/memory_insights.build_review()` computes, from the real memory:
win rate / expectancy / avg-RR by **weekday, symbol, strategy, session, setup
grade**; best/worst setups & sessions; the **mistake library** (ranked by
frequency, flags repeats); **winning patterns**; average hold; and
Sharpe/Sortino/expectancy/max-drawdown (Sharpe/Sortino reuse
`performance._risk_adjusted`, per-trade R basis).

**Coaching is sample-gated.** A statement like *"You perform 27% better during
the London session"* is only emitted when the bucket is large enough
(`_MIN_BUCKET = 5`), and every claim carries its stage:
`early-signal (<10)` → `building` → `evidence (≥30)`. Thin data yields an
explicit *insufficient-data* / *no-signal* message instead of a fabricated edge.

Reviews run **nightly** (with weekly/monthly/yearly rollups) via the existing
`DailyTasks` hook, and can be triggered on demand.

## API (`routers/journal.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/trade-memory/trades` | trade timeline (`q`, `symbol`, `result`, `strategy`, `session`) |
| GET | `/trade-memory/ask?q=` | natural-language query |
| GET | `/trade-memory/insights` | pattern recognition + coaching |
| GET | `/trade-memory/mistakes` | mistake library |
| GET | `/trade-memory/reviews?period=` | persisted nightly/weekly/monthly/yearly reviews |
| GET | `/trade-memory/similar/{id}` | most similar trades |
| GET | `/trade-memory/{id}` | full 8-category memory |
| PATCH | `/trade-memory/{id}/notes` | attach manual note *(secret)* |
| DELETE | `/trade-memory/{id}` | permanently forget one trade *(secret)* |
| POST | `/trade-memory/backfill` | import already-closed journal trades *(secret)* |
| POST | `/trade-memory/reviews/run` | run reviews now *(secret)* |

## Dashboard

A dedicated **Memory** page (`src/pages/Memory.tsx`, sidebar → Memory) with:
a search / ask bar, a knowledge-base coaching panel, winning patterns, the
mistake library, session/weekday breakdowns, an expandable trade timeline (full
8-category detail + notes editor + "forget trade"), a lessons timeline, and
nightly/weekly/monthly/yearly review tabs.

## Guarantees

- No fabricated data — uncaptured fields are marked, never invented.
- Live trading stays hard-locked; this system is read/record only.
- Memory composition never blocks or breaks the trading path (fully guarded).
- Trades are remembered forever; the only removal path is an explicit delete.
