# Strategy Lab — System Review

A review of the nine-stage Strategy Lab against the goal of a single, connected
strategy operating system. Every finding below was measured against the code, not
inferred; where a number appears, the command that produced it is reproducible.

**Measured baseline (this review):**

| | |
|---|---|
| Backend | 31,778 lines · 92 services · 12 routers · **233 endpoints** |
| Frontend | 16,975 lines · 31 pages · 58 components |
| Tests | 153 files · **1,342 passing** |
| Largest JS chunk | `ui` at **1,014 KB** (ECharts, loaded on every page) |
| Distinct polled endpoints | **78**, most on a 2-second interval |
| Timeframe→seconds maps | **6 copies**, with differing contents |

The platform is substantially more complete than most at this stage: one shared
engine, evidence-based AI output, and refusal semantics enforced by tests rather
than by convention. The findings below are therefore mostly about **connection,
attribution and cost**, not about missing capability.

---

## 1 · The single biggest gap: the lifecycle is not a lifecycle

The nine stages exist and work. They are also spread across **seven pages in two
different navigation groups, plus one route that is not in the sidebar at all**:

| Stage | Lives in | Nav group |
|---|---|---|
| 1. AI Strategy Agent | Strategy Studio | Trading |
| 2. Backtesting | Backtesting (+ Simulation) | Trading |
| 3. AI Strategy Review | *inside* Strategy Studio | Trading |
| 4. Paper Trading | Paper Trading | Trading |
| 5. Replay | Replay | Trading |
| 6. Live Deployment | Live Trading | Trading |
| 7. AI Monitoring Agent | Bot Health | **System** |
| 8. Marketplace | Strategies | **hidden route** |
| 9. Versioning & Collaboration | *inside* Strategy Studio | Trading |

Nothing tells a trader where a given strategy *is* in that progression, what it
still needs, or what the next action is. A user finishing a backtest has no
affordance pointing at the review; a user whose strategy is deployed has no
indication that monitoring lives on a page filed under "System".

This is the difference between nine tools and one product, and it is the first
thing to fix. **Implemented in this pass** — see `services/strategy_lifecycle.py`.

---

## 2 · Paper trades carry no strategy attribution

`paper_trades` has columns for symbol, side, size, entry, stop, exit, pnl, rr and
timestamps — but **no strategy column**:

```sql
INSERT INTO paper_trades(id,alert_id,symbol,side,size,entry,stop,status,opened_at)
```

Consequences, all of which understate what the platform actually knows:

- "How did *this strategy* do in paper?" is unanswerable. The paper account is
  global; results belong to whatever the engine was running at the time.
- Switching deployed strategy silently mixes two strategies' trades into one
  track record.
- The AI Monitoring Agent compares a strategy's backtest against **the whole
  paper account**, which is correct only while one strategy has ever run.

This is the highest-value database change available, and it is small: one column,
one migration, one write-site. **Implemented in this pass.**

---

## 3 · Replay silently changes your strategy's timeframe

`services/replay.py`:

```python
if exec_tf not in TF_FACTORS:
    exec_tf = "15m"
```

`TF_FACTORS` covers only `1m`, `3m`, `5m`, `15m`. A 1h or 4h strategy opened in
Replay is **silently executed at 15m** — a different strategy from the one that
was backtested, which contradicts the rule that replay must share execution logic
with everything else.

The clamp also means the neighbouring `_TF_SECONDS[exec_tf]` lookup can never
raise, so this is a correctness and honesty problem rather than a crash.
**Fixed in this pass**: the substitution is reported instead of hidden.

---

## 4 · One concept, six definitions

Six separate timeframe→seconds maps, with different contents:

| File | Missing entries |
|---|---|
| `bot/data/synthetic.py` | `2h`, `6h`, `12h`, `1w` |
| `bot/data/resample.py` | — (complete) |
| `automation-hub/services/watchdog.py` | `3m`, `2h`, `6h`, `12h`, `1w` |
| `automation-hub/services/replay.py` | **`1h`**, `30m`, `2h`, `6h`, `12h` |
| `automation-hub/services/auto_engine.py` | `3m`, `2h`, `6h`, `12h`, `1w` |
| `automation-hub/data/integrity.py` | `3m`, `2h`, `6h`, `12h`, `1w` |
| `automation-hub/data/ws_feed.py` | `3m`, `2h`, `6h`, `12h`, `1w` |

No live bug today — each is only indexed with keys it happens to contain — but
this is exactly the shape that produced the timeframe bug fixed in #201: a fact
about the domain defined in several places drifts, and the drift is invisible
until something silently returns the wrong answer. **Consolidated in this pass.**

---

## 5 · Client cost

- **`ui` chunk is 1,014 KB** (gzip 345 KB), dominated by ECharts, and is loaded
  on every page including ones with no chart. Route-level lazy loading of the
  charting bundle is the single largest front-end win available.
- **78 distinct polled endpoints**, the majority on a 2-second interval. The
  shared poller already dedupes identical paths, pauses on hidden tabs and backs
  off on errors — the remaining cost is *how many distinct* endpoints a page
  subscribes to, not duplicate subscriptions.
- No server-driven push. A single SSE or WebSocket channel carrying account,
  positions and engine status would replace the three busiest polls outright.

---

## 6 · What is already right (and should not be "improved")

Worth stating plainly, because a review that only lists problems invites damage:

- **One engine.** `services/spec_runner.py` is the only place a spec becomes a
  backtest, and a test asserts no caller re-implements it or calls `simulate`
  directly.
- **Refusals are enforced, not documented.** The marketplace cannot accept
  performance numbers (no parameter exists). The monitoring agent has no
  code path that writes a spec. The change log is derived from stored snapshots.
  Each is pinned by tests that try to defeat it.
- **Honest unavailability.** `{"available": false, "note": ...}` is used
  consistently instead of empty-but-plausible output.
- **Tenancy seam.** Stores already accept a `tenant_id`; multi-user is a flag,
  not a rewrite.

---

## 7 · Prioritised task list

**P0 — connection and correctness** *(this pass)*

1. Strategy Lifecycle view: one place showing every stage's real state and the
   next action. ✅
2. Strategy attribution on paper trades (schema + migration + write-site). ✅
3. Replay: report the timeframe substitution instead of hiding it. ✅
4. Consolidate the six timeframe maps onto one definition. ✅

**P1 — cost and scale**

5. Lazy-load the charting bundle per route (~1 MB off first paint).
6. Replace the three busiest polls with one SSE stream.
7. Index `paper_trades(strategy, closed_at)` once attribution exists — the
   monitoring agent's per-strategy history query depends on it.
8. Page the decision archive and ledger endpoints; both currently return capped
   lists rather than pages.

**P2 — product depth**

9. Walk-forward validation (train/test split) in the review — the single
   strongest defence against the curve-fitting the tuner already warns about.
10. Strategy comparison across the library, not just versions of one strategy.
11. Marketplace search and tag facets (currently browse + sort only).
12. Per-strategy monitoring, so several deployed strategies are each watched
    against their own baseline.

**P3 — hardening**

13. Encrypt exchange API keys at rest (currently env-var only).
14. Extend rate limiting beyond `/login`, `/signup`, `/webhook` to the compute-
    heavy endpoints (`/strategy/sweep`, `/strategy/tune`, `/marketplace/publish`).
15. Audit-log every marketplace publish and share grant.

---

## 8 · Deliberately not recommended

- **Do not add a "quick backtest" path.** Every proposal to make backtesting
  faster by simplifying execution reintroduces the two-engine problem that Sprint
  4 spent its entire budget removing.
- **Do not let the AI apply its own suggestions.** The value of the review is
  that a human decides; automating it converts an advisor into an unaudited
  trader.
- **Do not soften the marketplace's publish refusal.** "Fewer than 10 trades is
  refused" will feel harsh to a first-time publisher. It is the feature.
