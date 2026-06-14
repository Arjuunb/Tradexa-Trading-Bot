"""Automation Hub — FastAPI application (Phase 1).

Run locally:
    pip install -e ".[hub]"           # from the repo root (fastapi + uvicorn)
    cd automation-hub && uvicorn app:app --reload

Flow: Login -> Dashboard -> Create Bot -> Choose Strategy -> Select Exchange ->
Set Risk Rules -> Paper Trade -> Review Results -> (Deploy Live*) -> Monitor.
*Live execution is Phase 5; Phase 1 runs everything in paper mode.

Phase 1 is single-process and in-memory: one operator (configured credentials),
an in-memory BotManager, and paper runs over historical/synthetic data. The
package layout (bots/ strategies/ exchanges/ execution/ risk/ data/ ...) is the
production shape later phases fill in.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

# Make the sibling packages (bots, dashboard, strategies, ...) importable
# whether launched via uvicorn from this dir or imported by the test suite.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402

from config import settings  # noqa: E402
from bots.manager import BotManager  # noqa: E402
from bots.registry import EXCHANGES, STRATEGIES, exchange_label, strategy_label  # noqa: E402
from dashboard import widgets as w  # noqa: E402
from dashboard.overview import render_overview  # noqa: E402
from database.models import BotConfig, BotMode, RiskRules  # noqa: E402

app = FastAPI(title=settings.app_name)
manager = BotManager()

# token -> username (Phase 1 in-memory session store)
_sessions: dict[str, str] = {}
COOKIE = "hub_session"


# --------------------------------------------------------------- auth helpers
def _user(request: Request):
    return _sessions.get(request.cookies.get(COOKIE, ""))


def _require(request: Request):
    """Return username or a RedirectResponse to /login."""
    u = _user(request)
    return u if u else RedirectResponse("/login", status_code=303)


# ----------------------------------------------------------------------- login
@app.get("/login", response_class=HTMLResponse)
def login_form(error: str = "") -> str:
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Login · {w.esc(settings.app_name)}</title><style>{w._CSS}</style></head>
<body><form class="login" method="post" action="/login">
<h1>⚡ {w.esc(settings.app_name)}</h1>
<p>Sign in to your automation workspace.</p>
<label>Username</label><input name="username" autofocus value="admin">
<label>Password</label><input name="password" type="password">
<div style="margin-top:16px"><button class="btn" style="width:100%" type="submit">Log in</button></div>
{err}</form></body></html>'''


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    if username == settings.username and password == settings.password:
        token = secrets.token_urlsafe(24)
        _sessions[token] = username
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login?error=Invalid+credentials", status_code=303)


@app.post("/logout")
def logout(request: Request):
    _sessions.pop(request.cookies.get(COOKIE, ""), None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ------------------------------------------------------------------- dashboard
@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    return HTMLResponse(render_overview(manager, user=u))


# ------------------------------------------------------------------------ bots
@app.get("/bots", response_class=HTMLResponse)
def bots_page(request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    bots = manager.list()
    if bots:
        rows = "".join(
            f"<tr><td><b>{w.esc(b.config.name)}</b></td>"
            f"<td>{w.esc(strategy_label(b.config.strategy))}</td>"
            f"<td>{w.esc(exchange_label(b.config.exchange))}</td>"
            f"<td>{w.esc(b.config.symbol)}</td>"
            f"<td>{w.esc(b.config.mode.value)}</td>"
            f"<td>{w.state_badge(b.runtime.state.value)}</td></tr>"
            for b in bots
        )
        table = (f'<div class="card"><table><thead><tr><th>Name</th><th>Strategy</th>'
                 f'<th>Exchange</th><th>Symbol</th><th>Mode</th><th>State</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>')
    else:
        table = '<div class="card"><div class="empty">No bots yet.</div></div>'
    new_btn = '<a class="btn" href="/bots/new">+ Create Bot</a>'
    body = w.topbar("Bots", new_btn) + table
    return HTMLResponse(w.page(title="Bots", active="bots", body=body,
                               app_name=settings.app_name, user=u))


@app.get("/bots/new", response_class=HTMLResponse)
def new_bot_form(request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    strat_opts = "".join(
        f'<option value="{k}"{"" if ready else " disabled"}>{w.esc(label)}'
        f'{"" if ready else " (coming soon)"}</option>'
        for k, (_c, label, ready) in STRATEGIES.items()
    )
    exch_opts = "".join(
        f'<option value="{k}"{"" if ready else " disabled"}>{w.esc(label)}'
        f'{"" if ready else " (coming soon)"}</option>'
        for k, (label, _cls, ready) in EXCHANGES.items()
    )
    form = f'''<div class="card"><form method="post" action="/bots"><div class="formgrid">
<div><label>Bot name</label><input name="name" value="My Bot" required></div>
<div><label>Symbol</label><input name="symbol" value="{w.esc(settings.default_symbol)}"></div>
<div><label>Strategy</label><select name="strategy">{strat_opts}</select></div>
<div><label>Exchange</label><select name="exchange">{exch_opts}</select></div>
<div><label>Timeframe</label><select name="timeframe">
<option>5m</option><option>15m</option><option selected>1h</option></select></div>
<div><label>Mode</label><select name="mode">
<option value="paper" selected>Paper</option><option value="live">Live (Phase 5)</option></select></div>
<div><label>Risk per trade (%)</label><input name="risk_per_trade" type="number" step="0.1" value="1.0"></div>
<div><label>Max daily loss (%)</label><input name="max_daily_loss" type="number" step="0.1" value="3.0"></div>
</div><div style="margin-top:16px"><button class="btn" type="submit">Create Bot</button>
<a class="btn btn-ghost" href="/bots" style="margin-left:8px">Cancel</a></div></form></div>'''
    body = w.topbar("Create Bot") + form
    return HTMLResponse(w.page(title="Create Bot", active="bots", body=body,
                               app_name=settings.app_name, user=u))


@app.post("/bots")
def create_bot(
    request: Request,
    name: str = Form(...),
    strategy: str = Form("ema"),
    exchange: str = Form("binance"),
    symbol: str = Form("BTCUSDT"),
    timeframe: str = Form("1h"),
    mode: str = Form("paper"),
    risk_per_trade: float = Form(1.0),
    max_daily_loss: float = Form(3.0),
):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    rules = RiskRules(
        risk_per_trade_pct=max(risk_per_trade, 0.01) / 100.0,
        max_daily_loss_pct=max(max_daily_loss, 0.1) / 100.0,
        max_open_positions=settings.max_open_positions,
    )
    cfg = BotConfig(
        name=name, strategy=strategy, exchange=exchange, symbol=symbol,
        timeframe=timeframe, mode=BotMode(mode), risk=rules,
        starting_cash=settings.starting_cash,
    )
    manager.create(cfg)
    return RedirectResponse("/bots", status_code=303)


def _bot_action(request: Request, action):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    try:
        action()
    except Exception:  # noqa: BLE001 — illegal transition / missing bot -> back to dashboard
        pass
    return RedirectResponse("/", status_code=303)


@app.post("/bots/{bot_id}/start")
def start_bot(bot_id: str, request: Request):
    return _bot_action(request, lambda: manager.start(bot_id))


@app.post("/bots/{bot_id}/go-live")
def go_live_bot(bot_id: str, request: Request):
    # Phase 2: stream bars through the live engine (replay-driven demo).
    return _bot_action(request, lambda: manager.start_live(bot_id))


@app.post("/bots/{bot_id}/pause")
def pause_bot(bot_id: str, request: Request):
    return _bot_action(request, lambda: manager.pause(bot_id))


@app.post("/bots/{bot_id}/stop")
def stop_bot(bot_id: str, request: Request):
    return _bot_action(request, lambda: manager.stop(bot_id))


@app.post("/emergency-stop")
def emergency_stop(request: Request):
    return _bot_action(request, lambda: manager.emergency_stop_all())


# ------------------------------------------------------- secondary nav pages
def _simple_page(request: Request, title: str, active: str, body_inner: str):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    body = w.topbar(title) + body_inner
    return HTMLResponse(w.page(title=title, active=active, body=body,
                               app_name=settings.app_name, user=u))


@app.get("/strategies", response_class=HTMLResponse)
def strategies_page(request: Request):
    rows = "".join(
        f"<tr><td><b>{w.esc(label)}</b></td><td>{w.esc(k)}</td>"
        f"<td>{w.state_badge('Running' if ready else 'Created')}</td></tr>"
        for k, (_c, label, ready) in STRATEGIES.items()
    )
    inner = (f'<div class="card"><h2>Available Strategies</h2><table><thead><tr>'
             f'<th>Strategy</th><th>Key</th><th>Status</th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')
    return _simple_page(request, "Strategies", "strategies", inner)


@app.get("/paper-trading", response_class=HTMLResponse)
def paper_page(request: Request):
    from database.models import BotState
    bots = [b for b in manager.list() if b.runtime.state == BotState.PAPER]
    if bots:
        rows = "".join(
            f"<tr><td><b>{w.esc(b.config.name)}</b></td>"
            f"<td>{b.runtime.metrics.get('num_trades',0)}</td>"
            f"<td>{b.runtime.metrics.get('win_rate',0)*100:.0f}%</td>"
            f"<td class='{'pos' if b.runtime.pnl_today>=0 else 'neg'}'>"
            f"{settings.currency}{b.runtime.pnl_today:,.2f}</td></tr>"
            for b in bots
        )
        inner = (f'<div class="card"><h2>Paper Bots</h2><table><thead><tr><th>Bot</th>'
                 f'<th>Trades</th><th>Win rate</th><th>P&L today</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>')
    else:
        inner = ('<div class="card"><div class="empty">No paper bots running. '
                 'Create a bot (paper mode) and press Start.</div></div>')
    return _simple_page(request, "Paper Trading", "paper", inner)


@app.get("/risk-center", response_class=HTMLResponse)
def risk_page(request: Request):
    bots = manager.list()
    cur = settings.currency
    daily_loss = -sum(min(0.0, b.runtime.pnl_today) for b in bots)
    limit = settings.max_daily_loss_pct * settings.starting_cash
    worst_dd = min((b.runtime.metrics.get("max_dd", 0.0) for b in bots), default=0.0)
    summary = manager.summary()

    halted = [b for b in bots if b.runtime.halt_reason]
    if halted:
        rows = "".join(
            f"<tr><td><b>{w.esc(b.config.name)}</b></td>"
            f"<td class='neg'>⛔ {w.esc(b.runtime.halt_reason)}</td></tr>"
            for b in halted
        )
        halts = (f'<div class="card"><h2>Tripped Circuit Breakers</h2>'
                 f'<table><tbody>{rows}</tbody></table></div>')
    else:
        halts = ('<div class="card"><h2>Tripped Circuit Breakers</h2>'
                 '<div class="empty">None — all bots within risk limits.</div></div>')

    inner = (
        '<div class="card"><h2>Risk Center</h2>'
        f'<div>Daily loss: <b>{cur}{daily_loss:,.0f}</b> / {cur}{limit:,.0f}</div>'
        f'<div style="margin-top:8px">Worst bot drawdown: <b class="neg">{worst_dd*100:.2f}%</b></div>'
        f'<div style="margin-top:8px">Active bots: <b>{summary["running"] + summary["paper"]}</b></div>'
        '</div>'
        '<div class="card"><h2>Live Circuit Breakers</h2>'
        '<table><thead><tr><th>Breaker</th><th>Action</th></tr></thead><tbody>'
        f'<tr><td>Daily loss &gt; {settings.max_daily_loss_pct*100:.0f}% of equity</td>'
        '<td>Halt bot + alert</td></tr>'
        '<tr><td>Max drawdown breach</td><td>Halt bot + alert</td></tr>'
        '<tr><td>Consecutive-loss streak</td><td>Halt bot + alert</td></tr>'
        '<tr><td>Emergency stop (manual)</td><td>Halt all bots immediately</td></tr>'
        '</tbody></table>'
        '<p class="dim" style="margin-top:10px">Enforced live by risk/guards.py after every '
        'bar; the engine also applies the daily-loss kill switch + post-loss cooldown during runs.</p></div>'
        + halts
    )
    return _simple_page(request, "Risk Center", "risk", inner)


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, bot: str = ""):
    from dashboard.analytics import render_analytics
    return _simple_page(request, "Analytics", "analytics",
                        render_analytics(manager, bot_id=bot or None))


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    lines = []
    for b in manager.list():
        for ev in b.runtime.events[-40:]:
            lines.append(f"[{b.config.name}] {ev.get('type')} "
                         f"{ev.get('symbol','')} {ev.get('reason','')}".strip())
    inner = ('<div class="card"><h2>Logs</h2>'
             + ('<pre style="white-space:pre-wrap;color:#9fb0c0">'
                + w.esc("\n".join(lines[-200:])) + '</pre>'
                if lines else '<div class="empty">No logs yet.</div>')
             + '</div>')
    return _simple_page(request, "Logs", "logs", inner)


@app.get("/live-trading", response_class=HTMLResponse)
def live_page(request: Request):
    inner = ('<div class="card"><h2>Live Trading</h2>'
             '<p class="dim">Live order routing, real fills and multi-bot supervision land in '
             'Phase 5. The execution/ and exchanges/ packages already expose the interfaces; '
             'connect API keys in Settings to enable.</p></div>')
    return _simple_page(request, "Live Trading", "live", inner)


@app.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request):
    tg = "configured" if settings.telegram_token else "not configured"
    inner = (f'<div class="card"><h2>Notifications</h2>'
             f'<div>Telegram: <b>{tg}</b></div>'
             '<p class="dim" style="margin-top:10px">Telegram / Email / Discord channels are '
             'wired through the notifications/ package (Phase 5).</p></div>')
    return _simple_page(request, "Notifications", "notifications", inner)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    inner = (f'<div class="card"><h2>Settings</h2>'
             f'<div>Operator: <b>{w.esc(settings.username)}</b></div>'
             f'<div>Default exchange: <b>{w.esc(settings.default_exchange)}</b></div>'
             f'<div>Currency: <b>{w.esc(settings.currency)}</b></div>'
             f'<div>Starting cash: <b>{settings.currency}{settings.starting_cash:,.0f}</b></div>'
             '<p class="dim" style="margin-top:10px">Configure via environment variables / .env '
             '(HUB_USERNAME, HUB_PASSWORD, HUB_EXCHANGE, TELEGRAM_BOT_TOKEN, …).</p></div>')
    return _simple_page(request, "Settings", "settings", inner)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}
