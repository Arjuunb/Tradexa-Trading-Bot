# Strategy Lifecycle — Idea → Deployment → Monitoring → Collaboration

The Strategy Lab covers the full loop a trader walks: describe an idea in plain
English, compile it into executable rules, test it, analyse it, run it, watch it,
and share it. This document records where each stage lives and — more usefully —
what each stage is *forbidden* from doing, because most of the engineering here
is in the refusals.

## One engine, everywhere

Backtesting, paper trading, replay and live all run the same code path
(`strategies/custom.simulate` over `bot/tradecore`). Nothing in this lifecycle
introduces a second execution model, a "quick" simulator, or a separate scoring
routine. When the marketplace publishes a number, the AI review scores a
strategy, the tuner measures a variant, or the monitor computes a baseline, they
all call the same simulate path — which is what makes those numbers comparable
to each other and reproducible by the person reading them.

That claim used to be true but fragile: five call sites each wired up
`get_bars` → `TradeBrain` → `simulate` themselves, with the quality-filter and
min-score defaults copy-pasted into each, and nothing stopping one from drifting.
`services/spec_runner.py` is now that wiring, once. A test asserts none of the
callers re-implements it or calls `simulate` directly, so the claim above is
enforced rather than asserted.

| Stage | Where | Key refusal |
|---|---|---|
| 1. AI Strategy Agent | `services/strategy_agent.py` | Never invents a rule. Unclear phrasing becomes a clarifying question, not a guess. |
| 2. Backtesting | `strategies/custom.py`, `services/backtest_lab.py` | Real historical bars only. |
| 3. AI Strategy Review | `services/strategy_review.py`, `strategy_scorecard.py`, `strategy_optimizer.py`, `strategy_tuner.py`, `strategy_sweep.py` | Every claim carries its statistic. Anything the trade record can't support lands in `not_derivable`. |
| 4. Paper Trading | `execution/paper_engine.py` | Same execution logic as live. |
| 5. Replay | `services/replay.py` | Shares `TradeManager` with live (S4.4). |
| 6. Live Deployment | `services/auto_engine.py`, `services/broker.py` | Live stays behind the safety gate. |
| 7. AI Monitoring Agent | `services/monitor_agent.py` | Never modifies a strategy. `auto_modify` is always false. |
| 8. Marketplace | `services/strategy_publisher.py` | Cannot accept performance numbers from a publisher. |
| 9. Versioning & Collaboration | `services/custom_store.py`, `services/strategy_collab.py` | Change log is derived, never authored. |

## 7 · AI Monitoring Agent

Answers one question the other monitors did not: **is the live strategy still
the strategy you tested?**

The baseline is *recomputed* from the spec rather than stored, so it cannot
drift out of sync when someone edits a rule. Live metrics come from real closed
paper trades. Both sides therefore came out of one engine.

Findings: performance deviation (win rate / profit factor / expectancy),
drawdown beyond the tested range, trade-frequency collapse, volatility outside
the tested ATR band, and slippage worse than the fill model assumes.

Gating that matters:

- Trade-based verdicts are suppressed below `MIN_LIVE_TRADES` (15). A deviation
  call from four trades is worse than no call.
- Volatility and slippage checks need no trade sample, so they run immediately —
  including when there is no baseline at all.
- Trades with no R are excluded, not counted as 0R. Counting them would drag
  expectancy toward zero and manufacture a result.
- The endpoint reports its data source and refuses to let a bundled-sample feed
  present itself as current market volatility.

### Continuous mode

`services/monitor_runner.py` runs the same agent on a timer (default 15 min)
against `engine.deployed_spec` — what is *actually* running, not whatever is open
in the editor — and raises alerts through the ledger and notifier, the same path
the watchdog uses.

Three decisions worth stating, because each is a trap avoided:

- **The baseline is cached on the spec, not the clock.** Re-running a one-year
  backtest every cycle would burn minutes of CPU per hour recomputing a number
  that only changes when the strategy changes. The cache key is the spec's
  *definition*, so editing a rule invalidates it immediately and renaming or
  tagging does not. A 24h TTL still forces an eventual refresh, because the data
  behind the baseline does move. Measured: 0.2s cold, 0.00s warm.
- **Alerts have a per-finding cooldown** (default 1h). A strategy in drawdown
  produces the same finding every cycle; without a cooldown the operator learns
  to ignore the channel, which is worse than not alerting.
- **A built-in engine strategy reports "nothing to monitor", not "fine".**
  `deployed_spec` is cleared on every reconfigure that isn't a rule-spec deploy,
  so the agent can never silently compare against a strategy that stopped
  running.

One thing it deliberately does *not* block on: a feed that ignores the requested
candle size. The live engine fetches through the same `get_bars` path as the
baseline, so both sides get the same candles and the deviation verdict still
holds — what is wrong is the *label*, and that is reported as a
`timeframe_warning` beside the result. The sweep's identical check *does* block,
correctly: there the whole point is comparing one timeframe against another, so a
mismatch fabricates the answer.

Since the resampling fix (next section), no bundled-sample request trips either check —
they remain as a safety net for a live feed or a partial sync that returns the
wrong candle size.

`POST /strategy/monitor` (on-demand, arbitrary spec) ·
`GET /strategy/monitor/status` (last evaluation, no recomputation) ·
`POST /strategy/monitor/check` (force a cycle).

## Timeframes are real

The bundled sample CSVs are 1-hour candles, and `get_bars` used to return them
unchanged for **any** requested timeframe. A "4h strategy" was silently a 1h
strategy, and the multi-timeframe sweep was comparing a series against itself —
which is what the sweep's integrity check caught.

`bot/data/resample.py` fixes it at the source. Aggregating N candles into one is
exact — open of the first, high of the highest, low of the lowest, close of the
last, volume summed — so a 4h candle built from four real 1h candles *is* the 4h
candle. Four rules keep it honest:

- **Downsample only.** 1h → 4h is aggregation; 1h → 15m would mean inventing
  price action inside an hour nobody recorded, so it is refused and the request
  falls through to the next source in the ladder.
- **Whole multiples only.** 1h → 4h (×4) and 4h → 1d (×6) work; 4h → 6h does not.
- **Aligned to exchange buckets.** 4h candles start at 00:00 / 04:00 / 08:00 UTC,
  so a result can be checked against any chart.
- **No partial trailing candle.** A bucket short of its source candles is a bar
  the market has not closed; emitting it would let a strategy trade on it.

Measured on the bundled BTC sample: 2000×1h → 500×4h → 83×1d, every one passing
`timeframe_matches`.

The same aggregation applies to the **local synced store**: one `/data/sync` at
1h now also answers 4h, 6h, 12h and 1d from those real candles. Without it,
asking for 4h after syncing 1h dropped through to the bundled sample — swapping
real data for demo data purely because of a label.

**A limitation this exposes.** 2000 hourly candles is 83 days. That is plenty for
1h, thin for 4h (a typical spec produced 4 trades), and not enough for 1d. The
sweep flags thin cells and the review refuses to score them — but the real answer
is more history: run `/data/sync` to populate the local store, or set
`HUB_USE_LIVE_DATA=1`. The fix makes the candles correct; it cannot make the
sample longer.

## 8 · Marketplace

The hard problem is not listing strategies; it is that the incentive to lie
about performance is enormous. Transparency is enforced structurally:

- **`publish` takes a runner, not numbers.** The server executes the backtest.
  There is no parameter through which a publisher can supply a metric, so there
  is nothing to forge. A test asserts the signature rejects `metrics`,
  `results`, `verified` and `performance`.
- **An unverifiable strategy cannot be listed.** Fewer than
  `MIN_TRADES_TO_PUBLISH` (10) trades → publication is refused rather than
  listed with a caveat.
- **`history` is append-only.** Re-publishing replaces the headline metrics and
  appends a snapshot. A strategy that got worse shows a record that got worse.
- **There is no hide and no edit-metrics.** The only removal is `unpublish`,
  which deletes the whole listing — you cannot keep the storefront and drop the
  receipts.
- **Ratings belong to raters.** A publisher cannot rate their own strategy and
  has no code path to delete a bad review.
- **Sorting includes shallowest drawdown**, not only biggest return. A
  marketplace that can only rank by profit teaches people to chase profit.

`POST /marketplace/publish`, `GET /marketplace/listings`,
`POST /marketplace/listings/{id}/rate`, `POST /marketplace/follow`,
`POST /marketplace/listings/{id}/import`, `DELETE /marketplace/listings/{id}`.

## 9 · Versioning & Collaboration

Versioning already existed: every save that changes a definition snapshots the
previous state (`custom_store`, cap 30). Collaboration adds two halves that are
deliberately different in kind.

**Derived — cannot lie.** `diff_specs` and `changelog` are pure functions over
stored snapshots. Nobody writes a change note; the note *is* the difference
between two saved specs. This is what keeps "every version remains reproducible"
true: the log cannot drift from the artefact because it is computed from it.

```
v1: Initial recorded version.
v2: rsi value: 55 → 60
current: risk_per_trade_pct: 0.01 → 0.005
```

Rules are keyed by type so a parameter edit reads as one *change* rather than an
add plus a remove — the difference between a readable log and noise. Library
metadata (favourite, tags, folder) is excluded, so organising a library never
appears as a strategy edit.

**Authored — belongs to people.** Comments carry an author and an edit stamp;
only the author edits or deletes their own. Deleting a comment that has replies
tombstones it rather than orphaning the thread.

**Permissions** are per-strategy grants (`viewer` < `commenter` < `editor`)
layered on the account roles in `services/rbac.py`. Ownership is never
grantable, and an account role (`admin`, `operator`) is explicitly rejected as a
share role — accepting one would silently hand out privileges nobody chose to
share.

`GET /strategy/custom/{id}/changelog`, `GET .../compare`,
`GET|POST .../comments`, `PATCH|DELETE .../comments/{cid}`,
`GET .../shares`, `POST .../share`.

## Operator notes

Two environment variables are inert until set:

- `HUB_LLM_API_KEY` — activates natural-language strategy compilation in the AI
  Strategy Agent. Without it, the agent still validates and compiles structured
  input; it simply cannot parse free prose.
- `HUB_UNIFIED_FEES=1` — routes live paper fills through the same cost model the
  backtests use (S4.6), closing the live-vs-backtest cost gap.

One is on by default:

- `HUB_MONITOR_AGENT=0` stops the monitoring timer without disabling its
  endpoints — set it if you ever run multiple workers, since each would otherwise
  run its own loop and alert the same deviation once per worker.
