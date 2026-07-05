# Tradexa Trading Bot

A Python **multi-asset** trading bot with a **broker-adapter layer** so the same strategy code
runs on crypto (Binance / Coinbase / Kraken / Bybit / 100+ exchanges via
[ccxt](https://github.com/ccxt/ccxt)), US equities (Alpaca), and FX/CFDs
(OANDA). Includes a built-in **support / resistance + rejection-candle**
strategy, an event-driven **backtester**, a **risk manager**, and a **live
runner** that works against paper and real accounts with the same code.

## v0.3 quick start

The core is stdlib-only. No install needed for backtests, the CLI, the
HTML reporter, or the live web dashboard.

```bash
# Run a built-in demo backtest (synthetic data) and write an HTML report
python -m bot demo

# Backtest a CSV with default S/R strategy
python -m bot backtest --csv data/samples/BTC-USD.csv --report report.html

# Multi-asset portfolio backtest
python -m bot multi --csv data/samples/BTC-USD.csv --csv data/samples/ETH-USD.csv

# Walk-forward validation
python -m bot walkforward --csv data/samples/BTC-USD.csv --train 400 --test 100

# Live web dashboard with SSE event stream (stdlib http.server)
python -m bot dashboard --demo            # opens http://localhost:8765
```

### New v0.3 strategy switches (all default OFF, safe to opt-in)

- `trend_filter=True` + `atr_floor_pct` — block trades when EMA slope is flat or ATR is too small (T1)
- `vol_confirm=True` + `vol_sma_n`, `vol_mult` — require volume above N-bar average × multiplier (T2)
- `breakeven_at_r`, `partial_tp_r`, `partial_tp_frac` — move stop to BE and scale out at +R (T3)
- `max_hold_bars` — time-based exit (T4)
- `longs_only_in_uptrend=True` — directional bias filter (T5)

### Event bus + HTML reports

- `bot/events.py` — pub/sub `EventBus` with replay; wired into both backtester and multi_backtester
- `bot/reporting.py` — `render_report(result, output_path)` → self-contained HTML with embedded SVG equity curve
- `bot/dashboard.py` — ThreadingHTTPServer + Server-Sent Events for live monitoring


> ⚠️ This is educational software. Markets carry real risk. Always test with
> paper accounts first. The author and Perplexity assume no liability for
> trading losses.

---

## Install

The core is pure Python stdlib, so the base install pulls **no** third-party
packages. Venue SDKs and the YAML loader are optional extras:

```bash
pip install -e .            # core only (backtester, risk, metrics, reporting, CLI, dashboard)
pip install -e ".[dev]"     # + pytest + pyyaml (run the test suite)
pip install -e ".[crypto]"  # + ccxt        (crypto venues)
pip install -e ".[stocks]"  # + alpaca-py   (US stocks/options)
pip install -e ".[forex]"   # + oandapyV20  (FX/CFDs)
pip install -e ".[live]"    # every venue SDK + pyyaml
```

Installing exposes a `bot` console script (equivalent to `python -m bot`).
CI runs the suite on Python 3.10–3.12 (`.github/workflows/ci.yml`).

## Deploy to Vercel

The live SSE dashboard needs a long-running server, which Vercel's serverless
model can't host — but the self-contained HTML report is a perfect fit. The
repo ships a Python serverless function (`api/index.py`) that runs a backtest
per request and returns the report page:

```bash
npm i -g vercel        # or use the Vercel dashboard "Import Project"
vercel                 # preview deploy
vercel --prod          # production deploy
```

- `vercel.json` routes all traffic to `api/index.py` and bundles the `bot`
  package + sample data via `includeFiles`.
- `requirements.txt` is intentionally empty, so the build installs nothing.
- Query params: `GET /?symbol=BTC-USD&bars=2000&seed=1` — uses the bundled
  sample CSV when one exists for the symbol, otherwise deterministic synthetic
  data. `GET /health` returns `ok`.

---

## Architecture

```
bot/
├── types.py              # Bar, Signal, Order, Position, Fill, AccountSnapshot
├── risk.py               # RiskManager — sizing, daily-loss kill switch, cooldowns
├── backtester.py         # Event-driven backtest engine + metrics
├── live.py               # LiveRunner — same loop, real broker
├── brokers/
│   ├── base.py           # Broker abstract base class
│   ├── paper.py          # In-memory paper / backtest broker
│   ├── ccxt_broker.py    # Crypto (ccxt)
│   ├── alpaca_broker.py  # US stocks (alpaca-py)
│   └── oanda_broker.py   # FX/CFDs (oandapyV20)
└── strategies/
    ├── base.py           # Strategy ABC
    └── support_resistance.py  # S/R + rejection-candle strategy
```

The strategy talks to a generic `Broker` interface, so to add a new venue
you only implement one subclass.

---

## Strategy: Support/Resistance + Strong Rejection

1. **Find zones** — detect swing highs/lows via pivot points (default ±3
   bars), cluster nearby pivots into zones, and track touch counts. Stale
   zones expire after `max_zone_age` bars.
2. **Wait for a rejection at a zone**:
   - **LONG**: price pierces a support zone (low ≤ zone high) AND the bar
     closes back above the zone AND the bar is a **bullish pin bar** or
     **bullish engulfing**.
   - **SHORT**: symmetric setup at resistance.
3. **Risk-defined exits** — stop just beyond the rejection wick, take profit
   at `rr_target` × risk (default 2R).

All parameters live in `bot/strategies/support_resistance.py` and can be
overridden on construction.

---

## Quick start: backtest on synthetic data (no API keys)

```bash
git clone https://github.com/Arjuunb/Tradexa-Trading-Bot.git
cd Tradexa-Trading-Bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # ccxt/alpaca/oanda are optional
python -m examples.run_backtest
```

You'll see output like:

```
Start equity:   10,000.00
End equity:     10,742.31
Total return:   7.42%
Trades:         18
Win rate:       61.11%
Avg R:          0.84
Sharpe (ann.):  1.32
Max drawdown:   -3.91%
```

---

## Paper trading on Binance testnet

1. Get free testnet keys at https://testnet.binance.vision/.
2. Export them:
   ```bash
   export BINANCE_TESTNET_KEY=...
   export BINANCE_TESTNET_SECRET=...
   ```
3. Run:
   ```bash
   python -m examples.run_paper_crypto
   ```

The script uses `sandbox=True` so no real funds are touched.

## Paper trading on Alpaca (US stocks)

1. Sign up at https://alpaca.markets/ → get paper API keys.
2. ```bash
   export ALPACA_KEY=...
   export ALPACA_SECRET=...
   python -m examples.run_paper_stocks
   ```

## Going live (real money)

In `examples/run_paper_crypto.py` change `sandbox=True` → `sandbox=False` and
use real (not testnet) API keys. For Alpaca change `paper=True` → `False`.

Before doing this, **strongly recommended**:

- Run a full backtest on at least 12 months of historical data.
- Run paper trading for at least 2–4 weeks.
- Start with a small `risk_per_trade_pct` (e.g. 0.005 = 0.5% per trade).
- Verify the `max_daily_loss_pct` kill switch fires correctly in backtests.

---

## Risk manager

`bot/risk.py` enforces:

| Control | Default | Purpose |
|---|---|---|
| `risk_per_trade_pct` | 1% | Position size = `equity × pct ÷ stop-distance` |
| `max_open_positions` | 3 | Cap concurrent exposure |
| `max_daily_loss_pct` | 3% | Halt for the day when breached |
| `max_position_pct` | 25% | Cap notional per trade |
| `cooldown_bars_after_loss` | 5 | Pause after a stop-out (counts **bars**, not signals — strict wall-clock cooldown) |

The daily-loss kill switch anchors at the **first bar of each new UTC day**,
not at the first signal — losses incurred before any signal still count.

Pass a custom `RiskConfig` to `RiskManager` and inject it into the
`Backtester` / `LiveRunner`.

---

## Trailing stops

The `PaperBroker` supports a percentage trailing stop on a per-symbol basis:

```python
broker.set_trail_pct("BTC/USDT", 0.02)   # next entry gets a 2% trail
```

Semantics (industry-standard, next-bar effect):

- The stop only ever moves in the favourable direction — it ratchets, never
  loosens.
- A ratchet on bar N takes effect for the trigger check on bar N+1, so a
  newly-tightened stop can't fire on the same bar it moved.
- Works for longs and shorts.

Combine with a fixed `stop_loss` on the order to enforce a maximum loss until
the trail catches up.

## ATR-based volatility sizing (opt-in)

Set `atr_stop_mult` > 0 in `RiskConfig` to widen position sizing in choppy
markets. The risk manager uses the wider of (signal stop, `atr_stop_mult * ATR`)
as the per-unit risk — it can only ever make sizing more conservative:

```python
RiskConfig(risk_per_trade_pct=0.01, atr_stop_mult=2.0, atr_period=14)
```

The backtester computes ATR from its bar history and feeds it to the risk
manager on every bar; live runners do the same.

## Multi-symbol backtesting

`bot/multi_backtester.py` runs N strategies against N symbols sharing one cash
account and one risk budget. Bars are interleaved chronologically with a heap
so ordering is correct even when symbols have different bar timestamps.

```python
from bot.multi_backtester import MultiSymbolBacktester

mb = MultiSymbolBacktester(
    strategies={"BTC/USDT": ..., "ETH/USDT": ...},
    bars={"BTC/USDT": btc_bars, "ETH/USDT": eth_bars},
    starting_cash=50_000,
)
result = mb.run()
print(result.summary())   # also exposes result.per_symbol
```

See `examples/run_multi_backtest.py`.

## Walk-forward validation

Rolling (train, test) windows for catching overfitting:

```python
from bot.walkforward import walk_forward

report = walk_forward(
    bars=bars,
    build_strategy=lambda train: SupportResistanceRejection("X"),
    train_bars=2000, test_bars=500, step=500,
)
print(report.summary())
assert report.is_robust(min_sharpe=0.5, max_dd=-0.20)
```

The `build_strategy` callable receives the train slice; the strategy is then
backtested out-of-sample on the test slice. Any strategy whose Sharpe collapses
between train and test windows is overfit.

## Extended metrics

Every `BacktestResult.metrics` dict now also includes:

| Key | Definition |
|---|---|
| `cagr` | Compound annual growth rate |
| `sortino` | Sharpe but using downside-only deviation |
| `calmar` | CAGR / abs(max drawdown) |
| `profit_factor` | sum(wins) / sum(abs(losses)) |
| `expectancy` | Per-trade expected PnL: `wr*avg_win + (1-wr)*avg_loss` |

All formulas live in `bot/metrics.py` as pure functions and are independently
unit-tested.

## CSV data loader

Load OHLCV CSVs with the canonical or `time/date` header variants and ISO or
epoch timestamps:

```python
from bot.data import load_csv_bars
bars = load_csv_bars("data/btc_1h.csv")
```

## Exporting results

```python
result = bt.run()
result.export_equity_csv("out/equity.csv")
result.export_trades_jsonl("out/trades.jsonl")
print(result.summary(ascii_chart=True))   # equity sparkline on stdout
```

---

## Trade PnL, fees, and the SL/TP straddle

- **Trade PnL is reported net of fees.** Each trade dict carries `gross_pnl`
  (price-only) and `pnl` (gross − entry_fee − exit_fee). Metrics like total
  return, win rate, R-multiple and Sharpe all use the **net** value.
- **Same-bar SL/TP straddle resolution** — if a single bar's range contains
  both the stop and the target, the paper/backtest engine resolves it via
  `sl_first` (default `True`, the conservative choice: stop wins). Flip to
  `False` to model optimistic fills (target wins). Configurable per
  `PaperBroker` instance and exposed in YAML.

## Timeframe-aware Sharpe annualization

The backtester takes two extra kwargs that drive the annualization factor:

| Param | Values | Effect |
|---|---|---|
| `timeframe` | `"1m"`, `"5m"`, `"15m"`, `"1h"`, `"4h"`, `"1d"` | Bars per year |
| `market`    | `"24_7"` (crypto/FX) or `"rth"` (US equities) | 365 vs 252 trading days |

The computed annualization factor is also returned in the metrics dict as
`annualization_factor` for transparency.

---

## Config-driven runs (YAML)

Everything above can be driven from a YAML file via `bot/config.py` and
`examples/run_from_config.py`. Environment variables are interpolated with
`${VAR}` syntax so secrets stay out of the file. See
[`configs/example.yaml`](configs/example.yaml).

```bash
python -m examples.run_from_config configs/example.yaml
```

---

## Extending the bot

**Add a new venue** — subclass `bot/brokers/base.py:Broker`, implement the 7
abstract methods, then register it in `bot/brokers/__init__.py:get_broker`.

**Add a new strategy** — subclass `bot/strategies/base.py:Strategy` and
implement `generate(bar)`. Drop it into the backtester or live runner just
like the built-in one.

---

## Tests

```bash
pytest tests/ -v
```

---

## License

MIT. See [LICENSE](LICENSE).
