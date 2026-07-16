# Trading Simulation Engine — architecture & the fees upgrade

This documents the *existing* paper-trading simulator (which is already a
candle-driven exchange simulation, not an instant-close system) and the one
genuine realism gap that was closed: **trading fees**.

## What already exists (reused, not rebuilt)

The paper system is a candle-by-candle simulator built from these parts:

- **`services/auto_engine.py`** — the per-bar loop. On every candle it
  (`_process_bar`): fills resting **limit** orders when price trades through
  them (`_check_pending`, with gap-fills and TTL expiry), then checks the bar's
  **high/low range** to trigger **stop-loss / take-profit** (`_check_exit`) —
  it does *not* close on a signal instantly. Runs in replay or live-forward mode
  off the same `data.market_data.get_bars` feed the real bot uses (live CCXT
  when `HUB_USE_LIVE_DATA=1`).
- **`execution/paper_engine.py`** — the fill / P&L / ledger layer
  (`open` / `reduce` / `close`), driven by a pluggable **fill model**.
- **`services/fill_model.py`** — `RealisticFill` applies **spread + slippage +
  latency** (fill moves against you), **partial fills**, **rejection**, and now
  **commission**; maker (resting-limit) fills skip the spread.
- **`services/trade_manager.py`** — **trailing stop**, **break-even**, and
  **scale-out (partial take-profit)**, evaluated bar-by-bar.
- **`data/account_store.py`** — persists initial capital + equity snapshot so
  the account survives logout / restart; the ledger is the source of truth.
- Analytics (`/paper/equity-curve`, Strategy Proof) already cover equity curve,
  drawdown, win rate, profit factor, avg R, Sharpe/Sortino, per-symbol/session.

Because all of the above already works (and is covered by the backend suite),
the upgrade did **not** re-implement any of it.

## The gap that was closed: trading fees

Previously the engine booked spread/slippage as price impact but **no explicit
commission** (`trade_memory.py` literally read *"fees: 0.00 — fees not
modeled"*). Now:

- The fill model exposes `fee_pct(maker=…)` — a commission as a fraction of
  notional. `PerfectFill` returns **0** (so all existing behaviour and tests are
  unchanged); `RealisticFill` charges Binance-like defaults (taker `0.04%`,
  maker `0.02%`), configurable via `HUB_FILL_TAKER_FEE_PCT` /
  `HUB_FILL_MAKER_FEE_PCT`.
- `PaperExecutionEngine` deducts a **round-trip commission** (entry + exit
  notional, taker rate — a conservative paper assumption) from realized P&L on
  every `close` and proportionally on every partial `reduce`. Realized P&L —
  and therefore account equity — is now **net of fees**.
- `FillResult.fee` carries the commission for logging; `paper.fees_paid()` sums
  total commission across closed trades and is surfaced on `/paper/account`
  (`fees_paid`) and the Paper Trading account card.

Round-trip fee for a trade = `taker_rate × size × (|entry| + |exit|)`.

### Deliberately deferred: leverage / margin / liquidation

The engine is **spot / risk-based** (unleveraged — position size comes from
risk-per-trade, not margin). Adding leverage, margin and liquidation prices
would be a genuinely *new* synthetic capability, not a fix, so it was left out
pending a decision that the product actually simulates leveraged futures.

## Tests

`tests/test_paper_fees.py` (6): maker/taker fee rates, default engine charges
nothing (regression guard), round-trip fee deducted on long and short closes,
proportional fee on a partial close, and `fees_paid()` accounting.
