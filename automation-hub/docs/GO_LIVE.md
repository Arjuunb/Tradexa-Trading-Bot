# Going Live — Operations Runbook

Phases 2–5 ship the live machinery, but the in-app **Go Live** button runs a
*replay-driven dry run* by default (safe, no venue, no keys). This doc covers
the three steps to drive a bot against a **real exchange**: install, configure,
and enable real routing — plus how to deploy on a persistent host.

> ⚠️ Real trading risks real money. Start on a **testnet/sandbox** and with
> `dry_run=True` until you trust the behaviour.

---

## 1. Install

The engine core is stdlib-only; live trading needs the web extra plus the
venue SDK:

```bash
# from the repo root
pip install -e ".[hub,crypto]"     # FastAPI/uvicorn + ccxt (Binance/Bybit)
# pip install -e ".[hub,stocks]"   # + alpaca-py for US equities
```

## 2. Configure (`automation-hub/.env`)

```bash
cp automation-hub/.env.example automation-hub/.env
```

| Variable | Purpose |
|---|---|
| `HUB_USERNAME` / `HUB_PASSWORD` | operator login (change from admin/admin) |
| `HUB_SECRET` | random string for session/signing |
| `HUB_EXCHANGE` | default venue (`binance`) |
| `HUB_STARTING_CASH`, `HUB_CURRENCY` | display / sizing base |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | live venue credentials |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram alerts (optional) |
| `DISCORD_WEBHOOK_URL` | Discord alerts (optional) |
| `SMTP_HOST` / `ALERT_EMAIL_TO` (+ `SMTP_PORT/USER/PASS`) | email alerts (optional) |

Notifications **no-op** until at least one channel is configured, so alerts are
safe to leave on.

## 3. Run

```bash
cd automation-hub
uvicorn app:app --host 0.0.0.0 --port 8000     # http://localhost:8000
```

---

## 4. Enable real order routing

The pieces are already wired; you connect a real **broker** + **feed** and turn
off dry-run. Programmatically:

```python
from exchanges.binance import make_broker
from data.websocket import BrokerFeed

broker = make_broker(api_key=..., api_secret=..., sandbox=True)   # sandbox first!
feed   = BrokerFeed(broker, symbol="BTCUSDT", timeframe="1h")     # real-time bars

manager.start_live(
    bot_id,
    feed=feed,
    real_broker=broker,   # mirror every entry to the venue (bracket order)
    alerts=True,          # Telegram/Discord/email on fills, halts, completion
    dry_run=False,        # actually send orders (leave True to shadow-trade)
)
```

What happens then:
- `LiveBotRunner` streams real closed bars through the **same engine** the
  backtester uses (`Backtester.step`), so behaviour matches your backtests.
- `execution/live_bridge.RealOrderRouter` (an EventBus subscriber) mirrors each
  engine entry to the venue as a **bracket order** (market + SL/TP); exits are
  managed exchange-side.
- The Phase-3 circuit breakers still run every bar and **halt + alert** on
  daily-loss / drawdown / consecutive-loss breaches.

### Wiring the "Go Live" button to real routing

By default `POST /bots/{id}/go-live` calls `manager.start_live(bot_id)` (replay
dry run). To make the button trade live when keys are present, change that route
in `app.py`:

```python
@app.post("/bots/{bot_id}/go-live")
def go_live_bot(bot_id: str, request: Request):
    def _go():
        import os
        from exchanges.binance import make_broker
        from data.websocket import BrokerFeed
        bot = manager.get(bot_id)
        key, sec = os.environ.get("BINANCE_API_KEY"), os.environ.get("BINANCE_API_SECRET")
        if key and sec:
            broker = make_broker(api_key=key, api_secret=sec, sandbox=True)
            feed = BrokerFeed(broker, bot.config.symbol, bot.config.timeframe)
            manager.start_live(bot_id, feed=feed, real_broker=broker,
                               alerts=True, dry_run=False)
        else:
            manager.start_live(bot_id)   # fall back to replay dry run
    return _bot_action(request, _go)
```

Flip `sandbox=False` and `dry_run=False` only once verified on testnet.

---

## 5. Deploy (persistent host)

The Hub is **stateful** (in-memory bot manager + live threads), so it needs a
single long-running instance — **not** Vercel serverless. Any of Render /
Railway / Fly.io works:

- **Build:** `pip install -e ".[hub,crypto]"`
- **Start:** `cd automation-hub && uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Instances:** exactly **1** (no autoscaling — state lives in memory).
- **Env:** set the variables from step 2 in the host's dashboard.
- **Persistence:** bots are in-memory; a restart clears them. For durability,
  persist configs via `data/storage.py` (JSON) or wire the `database/` ORM
  (Phase 2+ roadmap).

The serverless **backtest report** (`api/index.py`) stays on Vercel and is
independent of the Hub.

---

## Safety checklist before `dry_run=False`

- [ ] Ran the strategy in **paper** and reviewed Analytics (win rate, drawdown).
- [ ] Verified on the venue **sandbox/testnet** with `dry_run=False`.
- [ ] Risk rules set per bot (risk %, daily-loss, max-drawdown, consecutive-loss).
- [ ] Alerts delivering to at least one channel.
- [ ] Single instance, keys scoped to **trade** (not withdraw), IP-allowlisted.
- [ ] You can hit **Emergency Stop** (halts every bot immediately).
