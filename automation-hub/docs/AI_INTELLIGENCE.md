# AI Trading Intelligence Engine

An on-demand decision layer that **composes the engine's existing intelligence**
into one pre-trade verdict. It does not replace strategy, risk, paper trading or
backtesting — it surfaces what the engine already computes per candle, on demand
for any symbol, and adds the two pieces that were missing (human confidence
levels + a full risk analysis with margin/liquidation).

## What already existed (reused, not rebuilt)

| Spec requirement | Existing implementation |
|------------------|-------------------------|
| Pre-trade analysis (trend, HTF, structure, **BOS**, **CHoCH**, **liquidity sweeps**, **order blocks / supply-demand**, **fair-value gaps**, S&R, EMA, volume, volatility) | `services/market_analysis.py::analyze`, `strategies/smc_strategy.py`, `strategies/brain.py` |
| Setup scoring (0–100, five categories) | `services/explain.py::build_scores` |
| Rule-by-rule explanation (PASS/FAIL/N/A) | `services/explain.py::build_checklist` |
| Reject weak trades / quality gate | `strategies/brain.py::TradeBrain`, `services/decision_gate.py` |
| Trade explanation (why / why-not / why-trust) | `services/coach.py::explain_trade`, `services/explain.py::build_cycle_report` |
| Post-trade review (why won/lost, mistakes, strengths, suggestions, quality score) | `services/trade_memory.py` (8-category memory + AI reflection), `services/decision_journal.py` |
| Pattern detection (best/worst session/symbol/strategy, mistakes, avg hold, avg RR) | `services/memory_insights.py`, `services/coach.py::attribution`; `/trade-memory/insights` |
| AI coach (daily review) | `services/coach.py::coach_review`; `/coach/review` |
| Market insights | `services/market_analysis.py`, `services/market_context.py` |
| Alerts | ledger alerts (`add_alert`) |
| Databases | `decisions`, `cycle_store`, `trade_memories`, `alerts` (reused per the brief) |

## What this adds (the genuine gap)

`services/ai_intelligence.py` — pure, testable:

- **`analyze_setup(symbol, timeframe, bars, side, equity, risk_pct, min_score,
  leverage, …)`** — fetches the market read, synthesizes a candidate setup
  (entry at price, ATR-multiple stop, reward:risk target), runs it through
  `build_scores` + `build_checklist` + `TradeBrain`, and returns one object:
  the **five-category score** (Trend / Market Structure / Volume / Risk
  Management / Confirmation), a **confidence level** (Very High … Very Low), the
  **BUY/SELL/WAIT/SKIP** decision with **reasons**, the **recommendation**, and
  the full market analysis + checklist.
- **`confidence_level(score)`** — maps the score to the five bands.
- **Risk analysis** — max loss, expected profit, risk %, reward:risk, position
  size, margin used, **liquidation price** (approximate isolated-margin, only
  above 1×), portfolio exposure, and an **excessive-risk warning**.
- **`trader_profile(insights)`** — distils strengths / weaknesses from the
  existing trade-memory insights (auto-updates as trades close).

### Endpoints (`routers/ai.py`)
- `GET /ai/analyze?symbol=&timeframe=&side=&leverage=&min_score=` — cached 20 s
  per key so dashboard polls don't re-fetch candles or recompute.
- `GET /ai/profile` — the personal trading profile.
- `GET /ai/confidence-levels` — the band legend.
- `GET /ai/confidence-accuracy` — calibration: do higher-confidence setups win more?
- `GET /ai/alerts` — the live alert feed (cached 30 s).
- `GET /ai/insights` — live market insights across the tracked symbols (cached 30 s).

### Confidence accuracy (calibration feedback loop)
`confidence_accuracy(rows)` buckets closed trades (from the trade memory:
`brain_score`/`confidence` + `result`) by confidence band and reports each
band's realized win rate / avg R. **Calibrated** = higher-confidence setups
actually win more (high-band win rate > low-band). Honest below ~10 graded trades.

### AI alert feed
`evaluate_alerts(analyses, risk, …)` produces the spec's six alert types from
real state — **strong setup**, **weak setup**, **risk exceeds limit**
(per-trade + portfolio exposure), **max daily loss / halt**, **outside session**,
and **high-impact news** (only when a source reports it) — ordered most-severe
first. `/ai/alerts` assembles the inputs from the engine's tracked symbols, the
live risk summary, and the pipeline's configured session window.

### Live market insights
`market_insights(reads)` turns the `market_analysis.analyze` reads into
natural-language insights — strong trend, break of structure, change-of-character
reversals, liquidity sweeps, rising/falling volume, and high-volatility warnings.
Every line is a real read of the candles; returns `[]` when nothing is notable.

### Dashboard
New **AI Intelligence** page (nav): decision / confidence / setup-score / market
bias widgets, the five-category score meter, the AI explanation (reasons +
unconfirmed checks), the risk-analysis row (max loss, expected profit, margin,
liquidation, exposure, warning), the auto-updating trading profile, and the
market read (bias, BOS, CHoCH, liquidity sweep, volume, volatility).

## Not built (honest)
- **Leverage/margin/liquidation are analytical** — the paper engine remains
  spot/risk-based; the AI layer *reports* margin & liquidation for a chosen
  leverage but does not execute leveraged positions.
- Post-trade review, pattern detection and the coach already existed and were
  reused rather than duplicated.

## Tests
`tests/test_ai_intelligence.py` (9): confidence bands, full analysis shape +
five categories, weak-setup rejection, risk-number consistency, leverage →
margin + liquidation (long below / short above entry), excessive-risk warning,
and trader-profile distillation. Full backend suite: **789 passed**.
