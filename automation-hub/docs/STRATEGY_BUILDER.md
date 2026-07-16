# No-Code Strategy Builder (Strategy Studio)

A visual builder that compiles to the **existing** spec engine — no second
execution path. Everything a user builds runs through the same
`strategies/custom.py::simulate` (backtest) and `CustomStrategyAdapter` (paper
deploy) the platform already uses, so a strategy works with backtesting, paper
trading and the AI analysis unchanged.

## What existed (reused, not rebuilt)
- **`strategies/custom.py`** — the spec engine: a JSON strategy is a condition
  tree (`{op: AND|OR, rules, negate}`) + stop/target/session/exit/risk, run by
  `simulate()` with fees, a risk gate and TradeBrain scoring. `validate()` +
  `describe()` already exist.
- ~15 blocks: EMA cross, RSI, SMA trend, MACD, breakout, volume, ATR, VWAP,
  Bollinger, pullback, support/resistance, liquidity sweep, FVG, BOS, CHoCH.
- **`services/custom_store.py`** + `/strategy/custom` endpoints: save / list /
  delete / duplicate / favorite / tags / **deploy to paper**.
- **`CustomBuilder.tsx`** — the original form-based builder.

## What this adds
- **5 new blocks** (`strategies/custom.py`): **ADX** (trend strength),
  **Supertrend**, **OBV**, **Stochastic RSI**, **Trend Direction** (HH/HL vs
  LH/LL) — each a bounded-window calc matching the existing pattern, with a
  `_phrase_rule` entry so `describe()` narrates them.
- **`services/strategy_builder.py`**:
  - `block_catalog()` — the palette grouped into Market Structure / Smart Money
    Concepts / Indicators / Price Action, each block with data-driven params, so
    the UI can't invent behaviour (every block maps 1:1 to a `_rule` branch).
  - `templates()` — 10 ready specs: SMC, ICT, Price Action, EMA Trend, Breakout,
    Scalping, Swing, Mean Reversion, Momentum, Trend Following.
  - `ai_review(spec, results)` — complexity / risk / expected behaviour /
    strengths / weaknesses / improvements / **estimated confidence**, grounded
    in a real backtest (never invented).
- **Endpoints** (`routers/analytics.py`): `GET /strategy/blocks`,
  `GET /strategy/templates`, `POST /strategy/ai-review`, plus library
  `POST /strategy/custom/{id}/favorite` and `/meta` (rename + folder).
- **Frontend** — a new **Strategy Studio** page: template gallery, categorized
  block palette (click to add), data-driven rule editor with AND/OR + per-rule
  NOT, stop/target/risk/session config, one-click **Backtest** and **AI Review**,
  JSON **export**, and the **library** (save / rename / favorite / duplicate /
  deploy-to-paper / delete).

## Integration (no duplicate engines)
A saved strategy is the same spec that `/strategy/custom/simulate` backtests and
`/strategy/custom/{id}/deploy` sends to the **paper engine** via
`CustomStrategyAdapter` — which routes through the same signal pipeline as every
other strategy, so paper trading, backtesting and AI analysis all work on it
with no new code path.

## Phase 2 — visual node canvas (done)
Strategy Studio now has a **Canvas** mode (toggle with Form) — a React Flow
node graph:
- **Condition** nodes (a rule block with editable params) → connect to an
  **AND/OR group** node → connect to the **Entry** (BUY/SELL) node.
- **Zoom, pan, mini-map, fit** (React Flow built-ins), drag to reposition,
  drag-to-connect, select + Delete to remove, and **undo / redo**.
- Groups can feed other groups, so the graph expresses nested logic like
  `(A AND B) OR C`. The engine's `evaluate()` was extended to **recurse into a
  nested group rule** (backward-compatible — flat specs are unchanged), so the
  canvas compiles to the same spec the simulator/paper engine already run.
- React Flow is lazy-loaded, so it only downloads when Canvas mode is opened.

Both modes edit the same `CustomSpec` — switch freely; Backtest / AI Review /
Save / Deploy work identically from either.

### Extra blocks (done)
Added **Ichimoku Cloud** (price above/below the cloud), **Order Block** (retest
of the last opposing candle before a structure break), and **Supply / Demand
Zone** (return to a base after an impulse). The palette is data-driven, so they
appear automatically in both the Form and Canvas builders.

### Still deferred
Exit *conditions* (indicator-exit, AI-exit) — these need the simulator's exit
loop to evaluate an exit rule tree each bar (a bigger engine change than the
entry blocks); the current exits are stop / target / break-even / trailing /
time-stop.

## Tests
`tests/test_strategy_builder.py` (9): new blocks evaluate + simulate, every
catalog block is a real engine rule, all 10 templates simulate, AI review with
and without a backtest, and library rename/folder/favorite. Full backend suite:
825 passed.
