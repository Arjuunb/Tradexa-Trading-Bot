# Deploying the live dashboard (real data, public URL)

The dashboard has two parts that deploy separately:

| Part | What | Where |
| --- | --- | --- |
| **Backend** | FastAPI + the autonomous strategy engine (runs continuously, generates real paper trades) | A **persistent** host — Render / Railway / Fly |
| **Frontend** | The React dashboard (static build) that polls the backend | Vercel (your existing project) |

> **Why not Vercel for the backend?** The engine runs as a long-lived background
> thread. Vercel Python functions are serverless (short-lived) and can't host a
> continuously running engine, so the backend needs a persistent web service.

The backend is containerized (`Dockerfile` at the repo root) and verified to run
with `uvicorn app:app` — the engine auto-starts and begins paper-trading on boot.

---

## 1. Deploy the backend (Render — free, recommended)

1. Push this branch to GitHub (already done).
2. In Render: **New + → Blueprint**, pick this repo. Render reads `render.yaml`
   and builds the `Dockerfile`. *(Or: New + → Web Service → Docker, same repo.)*
3. Set the env var **`HUB_WEBHOOK_SECRET`** to any strong string (remember it).
4. Deploy. Render gives you a URL like `https://automation-hub-api.onrender.com`.
5. Check it: open `https://<your-url>/health` → `{"status":"ok"}` and
   `https://<your-url>/engine/status` → `running: true` with rising `trades`.

**Railway / Fly** work the same way — both build the root `Dockerfile`; just set
`HUB_WEBHOOK_SECRET`. Locally you can run the exact same image with:
`docker build -t hub-api . && docker run -p 8000:8000 -e HUB_WEBHOOK_SECRET=secret hub-api`.

## 2. Point the frontend at it (Vercel)

In your Vercel project → **Settings → Environment Variables**:

| Key | Value |
| --- | --- |
| `VITE_API_BASE` | `https://<your-backend-url>` (no trailing slash) |
| `VITE_WEBHOOK_SECRET` | the **same** `HUB_WEBHOOK_SECRET` you set on the backend |

Then **redeploy** the Vercel project (env vars are baked in at build time). Open
the site → **Paper Trading**: live balance, positions, trades, decision log and
the Pause/Stop/Start controls now hit your real backend.

## 3. (Optional) Supabase as the source of truth

By default the backend uses local SQLite, which **resets when the host restarts**
(fine for a demo). For durable storage, use Supabase:

1. Create a Supabase project. In the SQL editor, run
   `automation-hub/data/ledger_schema.sql`.
2. On the backend host, set `SUPABASE_URL` and `SUPABASE_KEY`. The ledger
   switches to Supabase automatically (`get_ledger()`), and `pip install supabase`.

---

## Notes & limits

- **Free hosts sleep on idle.** Render free spins down after inactivity; the
  engine pauses until the next request wakes it. Paid tier / a cron ping keeps it
  always-on.
- **Engine config** (env): `HUB_AUTO_ENGINE` (1/0), `HUB_AUTO_SYMBOLS`
  (`BTCUSDT,ETHUSDT,SOLUSDT`), `HUB_AUTO_INTERVAL` (seconds per bar),
  `HUB_AUTO_TIMEFRAME` (default `4h` — the walk-forward-validated config),
  `HUB_AUTO_STRATEGY` (`brain` default / `supertrend` / `donchian` / `ensemble`).
- **Live real prices:** set `HUB_USE_LIVE_DATA=1` (ccxt is bundled) and the
  engine paper-trades the validated DecisionBrain on real Binance candles
  instead of synthetic data. `HUB_EXCHANGE` selects the venue (default binance).
- **Security:** read endpoints are public; control/engine actions require
  `HUB_WEBHOOK_SECRET`. Market data is local synthetic/sample — no exchange keys,
  paper-only, no real funds.
