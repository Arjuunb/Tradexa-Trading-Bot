# Phase 8 — Production Readiness & Paper-Trading Validation

Verification phase (no new "shiny" features). Confirms the merged 7-phase system
is stable, deployable, safe, and ready for an extended paper-trading validation
period. The only new surface is a **Paper Validation** panel, built entirely
from real stored trades + real system state.

> **Live trading remains hard-locked by design.** Nothing in this phase enables
> real-money trading. Paper mode stays the default.

---

## 1. What was checked

| Area | Result |
|---|---|
| All 7 phase merges present on `main` (#58–#64) | ✅ |
| Router split present (`routers/` — 8 domain files) | ✅ |
| New pages present (Bot Health, Strategy Proof, Journal) | ✅ |
| Backend test suite | ✅ (see commands) |
| Frontend typecheck + build | ✅ clean |
| Playwright e2e (incl. full click sweep) | ✅ all passing |
| No uncaught console errors on main pages | ✅ (click sweep asserts zero `pageerror`) |
| No broken API calls (4xx/5xx from the app itself) | ✅ (page-tour asserts none) |

## 2. Test commands

```bash
# Backend (from repo root)
cd automation-hub && python -m pytest -q

# Frontend typecheck + production build
cd automation-hub-dashboard && npx tsc --noEmit && npm run build

# End-to-end (deterministic mock backend, headless Chromium)
cd automation-hub-dashboard && npm run test:e2e
```

## 3. Deployment checks

Single-origin Docker image: the React build is bundled into the FastAPI app
(`Dockerfile` stage 1 → `automation-hub/webui`), so the Render URL serves the
identical UI Vercel serves.

| Item | Status / Location |
|---|---|
| Backend host | Render (`render.yaml`, Docker, `plan: free`) |
| Frontend host | Same image on Render **or** Vercel (`VITE_API_BASE` → backend URL) |
| Health endpoint | `GET /health` (Render `healthCheckPath`) + `GET /health/bot` |
| Env vars (Render) | `HUB_WEBHOOK_SECRET` (sync:false), `HUB_USERNAME`/`HUB_PASSWORD` (sync:false), `HUB_SECRET` (generateValue), `HUB_MAX_DAILY_LOSS=0.03`, `HUB_AUTO_ENGINE=1`, `HUB_USE_LIVE_DATA=1` |
| Webhook secret | Server-side only; control endpoints require the `X-Webhook-Secret` header |
| API base URL | `VITE_API_BASE` (frontend build-time), defaults to `http://localhost:8000` |
| CORS | `allow_origins=["*"]`, `allow_credentials=False` — safe: browsers never send cookies cross-origin, so auth relies on the same-origin cookie or the secret header |
| Cookie/session | HMAC-signed, `httponly`, `samesite=lax`, survives restarts |
| Static serving | `/assets` mounted; `index.html` served at `/` with runtime config |
| DB / persistent storage | SQLite under `HUB_DATA_DIR`. **Free tier disk is ephemeral** — history resets on redeploy unless a paid persistent disk is mounted and `HUB_DATA_DIR` points at it |

**Secret hygiene:** secrets are never logged and never committed (`.env` is
gitignored). One honest caveat: a Vercel-hosted frontend embeds
`VITE_WEBHOOK_SECRET` in its bundle (Vite inlines `VITE_*`), so on a split-origin
deploy that value is publicly readable. On the single-origin Render deploy the
cookie session is the primary auth and the embedded secret is not required.
Control actions are paper-only (pause/stop/start) — no money movement.

## 4. Safety checks (verified from real runtime state)

| Check | State |
|---|---|
| Live trading locked by default | ✅ `live_allowed=false`, `hard_locked=true` |
| Paper mode is default | ✅ `mode=paper`, `default_mode=paper` |
| Broker live connection not enabled | ✅ active broker = Paper, `broker_connected=false` |
| Emergency stop works | ✅ `POST /safety/test-emergency-stop` actually halts + restores, records the test |
| Max daily loss | ✅ active in production (`HUB_MAX_DAILY_LOSS=0.03`); code default stays 0 for deterministic tests |
| Max drawdown | ✅ active (20%) |
| Max open positions | ✅ active (3) |
| Decision logging | ✅ wired (`pipeline.journal`) |
| Skipped-trade logging | ✅ wired (`pipeline.skipped`) |
| Bot Health real status | ✅ `/health/bot` aggregates real engine/feed/risk/watchdog/errors |
| Strategy Proof real metrics | ✅ `/strategy/performance` (+ Sharpe/Sortino), `/strategy/health`, `/lab/walk-forward` |

## 5. Paper validation rules

The **Paper Validation** panel (`GET /validation/paper`, shown on Strategy Proof)
produces a single human-review verdict from real data. Eligibility is
**multi-factor** — one good metric can never carry it:

```
eligible = sample_size ≥ 30              (MIN_REVIEW; 50+ = "evidence")
           AND profit_factor ≥ 1.0 AND expectancy > 0   (proven edge)
           AND max_daily_loss + max_drawdown + decision_logging
               + emergency_stop_tested all active         (safety guards)
```

- **`eligible` never unlocks live trading.** It only signals that a human review
  may begin; live stays hard-locked regardless.
- Stages: `insufficient-sample` → `not-eligible` → `ready-for-review (early)`
  (≥30) → `ready-for-review (evidence)` (≥50).
- All numbers come from real closed paper trades, the real skip log
  (categorised: risk / quality / duplicate / session / safety / signal), and the
  live Safety Center state.

**How to run the validation period:** deploy, leave the engine running in paper
mode until it accumulates 30–50 closed trades, then read the Paper Validation
panel. Do not act on partial samples.

## 6. Known limitations

- **Free-tier persistence:** paper history/journal reset on redeploy unless a
  persistent disk is attached (`HUB_DATA_DIR`).
- **Per-strategy / per-timeframe proof:** paper trades run a single strategy on a
  single timeframe, so those breakdowns reflect the running config; cross-config
  robustness comes from Backtesting + walk-forward, not fabricated rows.
- **Split-origin secret embedding** (see §3) — prefer the single-origin deploy.
- **`app.py` auth/bots routes** are still server-rendered `@app` routes (not part
  of the `webhook_api` router split) — a possible future cleanup.

## 7. Next recommended phase

**Phase 9 — Paper validation run + live pre-flight.** Run the 30–50 trade
validation, review the panel, and (only if eligible) design a *manual, human-gated*
live pre-flight: broker connection check, tiny fixed size, dry-run order path,
and a second explicit confirmation — with live still defaulting to locked.
