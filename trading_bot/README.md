# Tradexa Bot Workspace (Python UI)

A professional, **Python-only** trading-bot workspace built with **Streamlit +
Plotly**. It runs as a standalone module today and is structured so it can be
folded into Tradexa later with no rewrite.

It does **not** reimplement the trading engine. It is a thin UI/service layer
over the existing `automation-hub` FastAPI backend — the single source of truth
for all data (paper engine, risk pipeline, ledger, backtester). Nothing here is
faked: if the backend has no data, the page says so.

## Run

```bash
pip install -r trading_bot/requirements.txt

# point the UI at the backend (defaults to http://localhost:8000)
export BOT_API_BASE="http://localhost:8000"
export BOT_WEBHOOK_SECRET="your-webhook-secret"   # for control/write endpoints

streamlit run trading_bot/app.py
```

Start the backend separately, e.g. `cd automation-hub && uvicorn app:app`.

## Sidebar pages (all real, no dead links)

Overview · Markets · Strategies · Backtesting · Simulation · Paper Trading ·
Live Trading · Portfolio · Analytics · AI Assistant · Risk Manager · Logs ·
Settings · Safety Center.

## Folder structure

| Path | Role |
|------|------|
| `app.py` | Streamlit entry + sidebar navigation |
| `config.py` | Settings (env-driven: API base, secret, timeouts) |
| `services/api.py` | **API layer** — client over the backend; the Tradexa integration seam |
| `models/schemas.py` | Pydantic schemas (strategy spec) |
| `charts/transforms.py` | Pure, testable chart data transforms (no plotting libs) |
| `charts/plots.py` | Plotly chart builders (lazy import, dark theme) |
| `safety/gates.py` | Pure safety-flow logic (progression, risk validation, live checklist) |
| `database.py` | Local SQLite for UI-only prefs (theme). Trading data never stored here |
| `ui/components.py` | Shared Streamlit helpers (KPI cards, banners, cached API client) |
| `pages/` | One module per sidebar page, each with `render()` |
| `tests/` | Unit tests for the API client, transforms and safety gates |

## Safety-first flow

Strategies cannot jump straight to live. Required progression:

**Backtest → Simulation → Paper Trading → Live Trading**

Live trading stays **locked** until: valid backtest results, simulation
results, paper-trading performance, valid risk settings, the user manually
confirms, **and** a real broker is connected. No broker is connected here, so
live is hardware-locked by design (see Safety Center / Live Trading pages).

## Data separation

Backtest, Simulation, Paper and Live datasets are kept strictly separate and
never cross-displayed. Simulated/paper performance is always labelled as such
and never presented as live results.

## Integrating into Tradexa

Tradexa connects at one seam: `services/api.py` (`HubAPI`). Point it at the
deployed backend (`BOT_API_BASE`), or wrap/replace those methods to call
Tradexa services directly. The pure modules (`charts/transforms.py`,
`safety/gates.py`, `models/schemas.py`) are framework-agnostic and reusable.

## Tests

```bash
python -m pytest trading_bot/tests -q
python -m compileall trading_bot          # syntax-check Streamlit pages
```
