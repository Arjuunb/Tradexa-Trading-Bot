# Automation Hub

A multi-bot trading control panel (FastAPI) built on top of the existing,
tested trading engine (`bot/` package at the repo root). The Hub adds login,
a dashboard, bot lifecycle management, paper trading, risk controls, analytics,
and (in later phases) live execution and notifications.

## Run it

```bash
# from the repo root — install the engine + hub web deps
pip install -e ".[hub]"

# launch
cd automation-hub
cp .env.example .env          # set HUB_USERNAME / HUB_PASSWORD
uvicorn app:app --reload      # http://127.0.0.1:8000  (login: admin / admin)
```

## User flow

```
Login → Dashboard → Automation Hub → Create Bot → Choose Strategy →
Select Exchange → Set Risk Rules → Paper Trade → Review Results →
Deploy Live → Monitor Bot
```

## Structure

```
automation-hub/
├── app.py              FastAPI app: routes, auth, pages
├── config.py           env-driven settings (.env)
├── dashboard/          overview, widgets (shell+sidebar+charts), alerts
├── bots/               manager, lifecycle (state machine), scheduler, registry
├── strategies/         base, ema, rsi (live), smc (Phase 2)
├── exchanges/          binance, bybit, alpaca adapters (over bot.brokers)
├── execution/          orders, positions, execution_engine
├── risk/               position_sizing, drawdown_guard, daily_limits
├── data/               market_data, websocket (Phase 2), storage (json)
├── paper_trading/      simulator (paper run == backtest)
├── backtesting/        engine/reports/metrics adapters over bot.*
├── database/           dataclass models + migrations/ (Phase 2 ORM)
├── notifications/      telegram / email / discord (Phase 5)
├── logs/  tests/  docs/
```

The new packages are **thin adapters** over the engine — no tested trading
logic was rewritten. `paper_trading.simulator` runs `bot.backtester.Backtester`;
`strategies` subclass `bot.strategies.base.Strategy`; `risk` wraps `bot.risk`.

## Build phases

- **Phase 1 (done):** login, dashboard, create bot, start/pause/stop,
  paper trading, EMA + RSI strategies, risk center, analytics, logs.
- **Phase 2:** live Binance data (websocket), scheduler-driven strategy
  execution, order simulator → live, position management.
- **Phase 3:** daily-loss limit, max-drawdown guard, emergency stop,
  consecutive-loss protection (engine enforces; surfaced in Risk Center).
- **Phase 4:** equity curve, win rate, profit factor, trade history (analytics).
- **Phase 5:** real orders, Telegram alerts, multi-bot supervision.

To trade against a real exchange, follow the **[Go Live runbook](GO_LIVE.md)**
(install extras, set keys, enable real routing, deploy on a persistent host).

## Deployment note

The Hub is **stateful** (in-memory bot manager + sessions), so it needs a
persistent host (Render / Railway / Fly / a VPS) running `uvicorn` — not
Vercel's stateless serverless functions. The serverless backtest report at
`api/index.py` remains the Vercel-friendly view.
```
