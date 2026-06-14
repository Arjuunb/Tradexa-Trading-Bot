# Multi-Asset Trading Bot

A Python trading bot with a **broker-adapter layer** so the same strategy code
runs on crypto (Binance / Coinbase / Kraken / Bybit / 100+ exchanges via
[ccxt](https://github.com/ccxt/ccxt)), US equities (Alpaca), and FX/CFDs
(OANDA). Includes a built-in **support / resistance + rejection-candle**
strategy, an event-driven **backtester**, a **risk manager**, and a **live
runner** that works against paper and real accounts with the same code.

> ⚠️ This is educational software. Markets carry real risk. Always test with
> paper accounts first. The author and Perplexity assume no liability for
> trading losses.

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
git clone https://github.com/Arjuun25/multi-asset-trading-bot.git
cd multi-asset-trading-bot
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
| `cooldown_bars_after_loss` | 5 | Pause after a stop-out |

Pass a custom `RiskConfig` to `RiskManager` and inject it into the
`Backtester` / `LiveRunner`.

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
