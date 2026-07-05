# Phase 9 — Paper Trading Execution & Evidence Collection

Operate Tradexa in **paper mode only** and collect real validation evidence
before any live-trading pre-flight. No new trading features, no live trading, no
faked trades/metrics/broker status, no strategy retune until enough evidence
exists.

> **Live trading is hard-locked and stays locked.** Nothing in this phase can
> enable real-money trading. A human review is required before any live
> pre-flight.

---

## Start date

- **Validation period start:** 2026-07-05 (set when the deploy is running with
  a persistent disk — see Persistence).

## Deployment info

- **Backend/UI:** single-origin Docker image on Render (`render.yaml`,
  `healthCheckPath: /health`). The React build is bundled into the FastAPI app,
  so the Render URL serves the same UI as Vercel.
- **Engine:** `HUB_AUTO_ENGINE=1` starts the autonomous paper engine on boot;
  `HUB_USE_LIVE_DATA=1` paper-trades the DecisionBrain on real Binance candles.
- **Risk guard:** `HUB_MAX_DAILY_LOSS=0.03` is set in `render.yaml` so the
  daily-loss kill switch is engaged in production.

## Persistence check result

- **Mechanism verified** (automated test `test_stores_persist_across_restart`):
  the skip log, decision journal, and safety state all survive a "restart"
  (a fresh store instance on the same file). Settings persist via
  `runtime_settings.json`; paper trades + journal live in SQLite under
  `HUB_DATA_DIR`.
- **Action required for the live deploy:** set **`HUB_DATA_DIR` to a persistent
  disk** (e.g. `/data` on a paid Render disk). On the free tier the disk is
  **ephemeral** — a redeploy or spin-down wipes paper history, so the 30–50
  trade sample would reset. Verify by redeploying once and confirming the trade
  count on the Paper Validation panel is unchanged.

## Validation rules (multi-factor — one metric can never carry it)

```
eligible = closed_trades ≥ 30                 (MIN_REVIEW; 50+ = "evidence")
           AND profit_factor ≥ 1.0 AND expectancy > 0      (proven edge)
           AND max_daily_loss + max_drawdown + decision_logging
               + emergency_stop_tested all active            (safety guards)
```

- `eligible` means **a human review may begin** — it NEVER unlocks live trading.
- Live stays hard-locked regardless of any metric.

## Required sample size

- **30 closed paper trades** — minimum for early review.
- **50+ closed paper trades** — stronger "evidence" stage. Prefer this.

## Failure conditions (do NOT proceed toward live if any hold)

- Sample below 30 closed trades.
- Profit factor < 1.0 or expectancy ≤ 0 (no proven edge).
- Daily report `trend.direction == "weakening"` over the recent window.
- Any safety guard inactive (daily loss / drawdown / decision logging /
  emergency-stop test not done).
- Max-drawdown circuit breaker or daily-loss kill switch tripped during the run.
- Repeated Bot Health errors, or the watchdog reporting a stalled feed / dead
  engine thread.

## Daily review checklist

Read once per day (endpoints, or the Paper Validation panel on Strategy Proof):

1. `GET /health` returns 200; Bot Health page loads with real status.
2. `GET /validation/daily-report` — closed-trade count, win rate, profit factor,
   expectancy, avg R, max drawdown, **trend (improving / stable / weakening)**.
3. New **skipped-trade reasons + categories** (risk / quality / duplicate /
   session / safety / signal).
4. **Risk events** (risk/safety-category skips, any auto-halt) and **health
   errors** in the report.
5. Safety Center: `live_allowed=false`, `hard_locked=true` still hold.
6. Live-review verdict: `eligible` and `stage`. Do not act on partial samples.

## Live trading remains locked

Every daily report ends with `live_trading: "LOCKED"` and the reminder that a
human review is required before any live pre-flight. There is **no automatic
live unlock** anywhere in the system.

## Endpoints used this phase

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness (Render health check) |
| `GET /health/bot` | full Bot Health snapshot |
| `GET /safety/live-readiness` | Safety Center gate state |
| `GET /validation/paper` | multi-factor validation verdict |
| `GET /validation/daily-report` | daily evidence digest + trend |
| `GET /skipped/trades`, `/skipped/summary` | skip log + categories |
| `GET /strategy/performance` | paper track record + Sharpe/Sortino |

## Next recommended phase

**Phase 10 — Manual, human-gated live pre-flight** (only if validation is
eligible after 50+ trades): broker connection check, tiny fixed size, dry-run
order path, and a second explicit human confirmation — with live still
defaulting to locked and every safety guard enforced.
