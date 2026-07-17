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

import queue
import secrets
import sys
from pathlib import Path

# Make the sibling packages (bots, dashboard, strategies, ...) importable
# whether launched via uvicorn from this dir or imported by the test suite.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Optional  # noqa: E402
from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse, RedirectResponse, StreamingResponse,
)

from config import settings  # noqa: E402
from bots.manager import BotManager  # noqa: E402
from bots.registry import EXCHANGES, STRATEGIES, exchange_label, strategy_label  # noqa: E402
from dashboard import widgets as w  # noqa: E402
from dashboard.overview import render_overview  # noqa: E402
from database.models import BotConfig, BotMode, RiskRules  # noqa: E402
from database.store import SqliteStore  # noqa: E402

app = FastAPI(title=settings.app_name)
# Phase 6/7: one SQLite store backs both bot persistence and user accounts.
# The first admin is seeded from HUB_USERNAME/HUB_PASSWORD. Tests override
# `manager` with an in-memory BotManager() but reuse `store` for auth.
store = SqliteStore(settings.db_path)
# Durable settings mirror: when SUPABASE_URL + SUPABASE_KEY are set, per-user
# settings persist to Supabase so they survive an ephemeral-disk restart (no
# more "defaults on every login") without needing a paid disk. No-op otherwise.
try:
    from data.settings_store import make_settings_mirror, SETTINGS_MIRROR_STATUS  # noqa: E402
    store.settings_mirror = make_settings_mirror()
    if store.settings_mirror is not None:
        print("[settings] durable Supabase mirror CONNECTED — settings survive redeploys.", flush=True)
    elif SETTINGS_MIRROR_STATUS["configured"]:
        print(f"[settings] Supabase configured but NOT working: {SETTINGS_MIRROR_STATUS['error']} "
              f"— settings will still reset on redeploy until this is fixed.", flush=True)
    else:
        print("[settings] no Supabase (SUPABASE_URL/KEY unset) — settings are local only "
              "and reset on an ephemeral-disk redeploy.", flush=True)
except Exception:  # noqa: BLE001 — never let settings persistence break boot
    pass
store.seed_admin(settings.username, settings.password)
manager = BotManager(store=store)

# M-7: fail closed on insecure defaults in production. render.yaml generates a
# strong HUB_SECRET, so a default here on a cloud host means misconfiguration —
# and a default session-signing key makes cookie forgery trivial. A default
# password is warned about loudly but not hard-blocked (so you're never locked
# out of your own deploy).
import os as _sec_os  # noqa: E402
_ON_CLOUD = bool(_sec_os.environ.get("RENDER") or _sec_os.environ.get("DYNO"))
_UNDER_TEST = "PYTEST_CURRENT_TEST" in _sec_os.environ or bool(_sec_os.environ.get("HUB_DEV"))
if _ON_CLOUD and not _UNDER_TEST:
    if settings.secret_key == "dev-insecure-secret":
        raise RuntimeError(
            "REFUSING TO BOOT: HUB_SECRET is unset (default session-signing key). "
            "Set HUB_SECRET to a strong random value (render.yaml does this with "
            "generateValue) before exposing this service — otherwise session "
            "cookies are forgeable.")
    if settings.password == "admin":
        import sys as _sec_sys
        print("\n" + "=" * 68 + "\n  SECURITY WARNING: HUB_PASSWORD is the default 'admin'.\n"
              "  Set a strong HUB_PASSWORD before real use.\n" + "=" * 68 + "\n",
              file=_sec_sys.stderr, flush=True)

# M-5: report the control-credential posture. Scoped = the webhook secret (shared
# with TradingView) can post alerts but not control the account.
if settings.scope_webhook_secret and settings.admin_key != settings.webhook_secret:
    print("[auth] webhook secret is SCOPED to /webhook — control requires the admin key.", flush=True)
elif settings.admin_key == settings.webhook_secret:
    print("[auth] admin key = webhook secret (set HUB_API_KEY + HUB_SCOPE_WEBHOOK=1 to decouple).", flush=True)

# Kyros Phase 1: TradingView webhook -> paper-execution -> ledger API.
# `webhook_api` also owns the process-wide paper account / ledger / control
# switch singletons; the dashboard pages below read them via the module so they
# always reflect live webhook activity.
import webhook_api  # noqa: E402
from webhook_api import router as webhook_router  # noqa: E402
app.include_router(webhook_router)

# The React dashboard runs on its own dev origin (Vite) and calls this API, so
# allow cross-origin during local development.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# Iframe embedding (e.g. inside the Tradexa app): set HUB_FRAME_ANCESTORS to the
# embedding origin(s) — e.g. "https://tradexa.app" or "'self' https://tradexa.app"
# — and browsers will allow ONLY those sites to frame the dashboard (clickjacking
# stays blocked everywhere else). Unset = header not sent (default behavior).
import os as _mw_os  # noqa: E402


@app.middleware("http")
async def _frame_ancestors(request, call_next):
    resp = await call_next(request)
    ancestors = _mw_os.environ.get("HUB_FRAME_ANCESTORS", "").strip()
    if ancestors:
        resp.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors}"
    return resp

# API protection: every data/control endpoint requires a signed-in session
# (cookie) or the webhook secret (header). Exempt: the auth flow itself, the
# TradingView webhook (it authenticates with the secret in its own handler),
# static assets, and "/" (which redirects anonymous visitors to /login).
_AUTH_EXEMPT = ("/login", "/signup", "/auth/", "/webhook", "/assets",
                "/favicon", "/docs", "/openapi.json", "/redoc", "/health", "/version")


@app.middleware("http")
async def _require_auth(request: Request, call_next):
    path = request.url.path
    exempt = _AUTH_EXEMPT
    # With the landing bundled, its public SPA routes bypass the API auth wall.
    # "/app" is exempt here but self-gates in its own handler (it carries the
    # control secret, so anonymous visitors are redirected to /login there).
    if _LANDING_READY:
        # H-2: exempt the SPA sub-routes ("/settings/profile", …) but NOT the
        # bare "/settings" API endpoint, which returns live strategy/risk config
        # and must stay session-gated. The landing serves only "/settings/{path}".
        exempt = exempt + ("/settings/", "/app")
    hdr = request.headers.get("x-webhook-secret")
    if (path == "/" or any(path.startswith(p) for p in exempt)
            or _user(request)
            or hdr == settings.admin_key
            or (not settings.scope_webhook_secret and hdr == settings.webhook_secret)):
        return await call_next(request)
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": "Sign in required"}, status_code=401)

# Single-origin UI: when the React build is present (copied into ./webui by the
# Docker image), serve it from this backend so Render shows the SAME dashboard as
# Vercel. Assets are mounted; index.html is served at "/" with runtime config
# injected (apiBase="" same-origin + the webhook secret). Without a build (tests/
# local), the legacy server-rendered dashboard is served instead.
import json as _json  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
_WEBUI = Path(__file__).resolve().parent / "webui"
_WEBUI_READY = (_WEBUI / "index.html").exists()

# Optional standalone landing / auth / settings SPA (tradexa-landing), bundled by
# the Docker image into ./landing. When present it becomes the PUBLIC front door
# at "/", and the session-gated dashboard moves under "/app". When absent (tests
# / local without the landing build) the dashboard keeps "/" exactly as before.
_LANDING = Path(__file__).resolve().parent / "landing"
_LANDING_READY = (_LANDING / "index.html").exists()

if _WEBUI_READY and (_WEBUI / "assets").exists():
    # dashboard assets move to /app/assets when the landing owns /assets
    _DASH_ASSETS = "/app/assets" if _LANDING_READY else "/assets"
    app.mount(_DASH_ASSETS, StaticFiles(directory=str(_WEBUI / "assets")), name="assets")
if _LANDING_READY and (_LANDING / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_LANDING / "assets")), name="landing-assets")


def _serve_react() -> HTMLResponse:
    html = (_WEBUI / "index.html").read_text(encoding="utf-8")
    cfg = ('<script>window.__HUB_CONFIG__='
           + _json.dumps({"apiBase": "", "secret": settings.admin_key})
           + '</script>')
    return HTMLResponse(html.replace("<head>", "<head>" + cfg, 1))


def _serve_landing(request: Optional[Request] = None) -> HTMLResponse:
    """The landing/settings SPA is public and never carries the control secret —
    EXCEPT for a signed-in operator, whose Settings pages (e.g. the live
    strategy switcher) drive the engine and need the same runtime config the
    dashboard gets. Anonymous visitors always receive the bare page."""
    html = (_LANDING / "index.html").read_text(encoding="utf-8")
    if request is not None and _user(request):
        cfg = ('<script>window.__HUB_CONFIG__='
               + _json.dumps({"apiBase": "", "secret": settings.admin_key})
               + '</script>')
        html = html.replace("<head>", "<head>" + cfg, 1)
    return HTMLResponse(html)


# Single-origin routing (only when the landing build is bundled): the public
# landing SPA owns "/", "/auth/*" and "/settings/*"; the dashboard lives at "/app"
# and stays session-gated. BrowserRouter paths need a real HTML response per route.
if _LANDING_READY:
    _LANDING_AUTH = ("login", "register", "forgot-password", "reset-password",
                     "verify-email", "two-factor", "session-expired")

    def _landing_page(request: Request) -> HTMLResponse:
        return _serve_landing(request)

    def _landing_sub(request: Request, path: str = "") -> HTMLResponse:  # noqa: ARG001 — path is the SPA route
        return _serve_landing(request)

    for _p in _LANDING_AUTH:
        app.add_api_route(f"/auth/{_p}", _landing_page, response_class=HTMLResponse, methods=["GET"])
    app.add_api_route("/settings/{path:path}", _landing_sub, response_class=HTMLResponse, methods=["GET"])

    @app.get("/app", response_class=HTMLResponse)
    @app.get("/app/{path:path}", response_class=HTMLResponse)
    def _dashboard_app(request: Request, path: str = ""):  # noqa: ARG001
        u = _require(request)
        if isinstance(u, RedirectResponse):
            return u
        return _serve_react() if _WEBUI_READY else HTMLResponse(render_overview(manager, user=u))



@app.on_event("startup")
def _start_auto_engine() -> None:
    """Start the autonomous strategy engine when the server boots (real signals
    -> paper execution -> ledger). Disabled under pytest and via HUB_AUTO_ENGINE=0."""
    import os
    backend = type(webhook_api.ledger).__name__
    print(f"[startup] ledger backend = {backend} "
          f"(Supabase active: {backend == 'SupabaseLedger'})", flush=True)
    if settings.auto_engine and "PYTEST_CURRENT_TEST" not in os.environ:
        webhook_api.engine.start()
        print(f"[startup] autonomous engine started — symbols={list(settings.auto_symbols)} "
              f"timeframe={settings.auto_timeframe} interval={settings.auto_interval}s", flush=True)
    else:
        print("[startup] autonomous engine NOT started "
              f"(auto_engine={settings.auto_engine})", flush=True)

# Phase 8: process-wide event hub for the live (SSE) dashboard.
from dashboard.stream import HubEventHub, sse_format  # noqa: E402
hub_events = HubEventHub()

# token -> username (legacy in-memory sessions; kept for test fixtures)
_sessions: dict[str, str] = {}
COOKIE = "hub_session"
SESSION_DAYS = 7


def _cookie_kwargs() -> dict:
    """Session-cookie attributes. Default SameSite=Lax (same-origin dashboard).
    Set HUB_COOKIE_SAMESITE=none to allow the dashboard to be embedded in an
    iframe on another site (e.g. the Tradexa app) — SameSite=None requires
    Secure, so it only works over HTTPS (which Render provides)."""
    import os
    samesite = os.environ.get("HUB_COOKIE_SAMESITE", "lax").lower()
    if samesite not in ("lax", "none", "strict"):
        samesite = "lax"
    kw = {"httponly": True, "samesite": samesite,
          "max_age": SESSION_DAYS * 86400}
    if samesite == "none":
        kw["secure"] = True
    return kw


# --------------------------------------------------------------- auth helpers
def _sign_session(username: str) -> str:
    """Stateless signed session token (survives server restarts — important on
    hosts that spin down): username|expiry|HMAC(secret, username|expiry)."""
    import hashlib
    import hmac as _hmac
    import time
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    msg = f"{username}|{exp}"
    # CR-1: sign with the server-only secret_key (HUB_SECRET), NOT the
    # webhook_secret — the webhook secret is embedded in every authed page, so
    # signing sessions with it would let any logged-in user forge an owner token.
    sig = _hmac.new(settings.secret_key.encode(), msg.encode(),
                    hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def _verify_session(token: str):
    import hashlib
    import hmac as _hmac
    import time
    try:
        username, exp, sig = token.rsplit("|", 2)
    except ValueError:
        return None
    msg = f"{username}|{exp}"
    good = _hmac.new(settings.secret_key.encode(), msg.encode(),
                     hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(sig, good):
        return None
    if int(exp) < time.time():
        return None
    return username if store.get_user(username) else None


def _user(request: Request):
    token = request.cookies.get(COOKIE, "")
    return _verify_session(token) or _sessions.get(token)


def _require(request: Request):
    """Return username or a RedirectResponse to /login."""
    u = _user(request)
    return u if u else RedirectResponse("/login", status_code=303)


def _signup_open() -> bool:
    """Signup creates the single OWNER account. It stays open only while the
    seeded default admin is the sole user — after that this hub has an owner."""
    return all(u.username == settings.username for u in store.list_users())


# ----------------------------------------------------------------------- login
def _auth_page(title: str, body: str) -> str:
    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{w.esc(title)} · Tradexa</title><style>{w._CSS}</style></head>
<body>{body}</body></html>'''


@app.get("/login", response_class=HTMLResponse)
def login_form(error: str = "") -> str:
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    signup = ('<p style="margin-top:12px">New here? '
              '<a href="/signup">Create your Tradexa account</a></p>'
              if _signup_open() else "")
    return _auth_page("Sign in", f'''<form class="login" method="post" action="/login">
<h1>⚡ Tradexa</h1>
<p>Sign in to your trading workspace.</p>
<label>Username</label><input name="username" autofocus>
<label>Password</label><input name="password" type="password">
<div style="margin-top:16px"><button class="btn" style="width:100%" type="submit">Sign in</button></div>
{err}{signup}</form>''')


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    # verify against hashed credentials; signed cookie survives restarts
    if store.authenticate(username, password) is not None:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, _sign_session(username), **_cookie_kwargs())
        return resp
    return RedirectResponse("/login?error=Invalid+credentials", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
def signup_form(error: str = "") -> str:
    if not _signup_open():
        return _auth_page("Sign up", '''<form class="login">
<h1>⚡ Tradexa</h1><p>This hub already has an owner account.</p>
<p><a href="/login">Sign in instead</a></p></form>''')
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    return _auth_page("Create account", f'''<form class="login" method="post" action="/signup">
<h1>⚡ Tradexa</h1>
<p>Create the owner account for this trading hub. There is exactly one —
it controls the bot, so pick a strong password.</p>
<label>Username</label><input name="username" autofocus>
<label>Password (8+ characters)</label><input name="password" type="password">
<label>Confirm password</label><input name="confirm" type="password">
<div style="margin-top:16px"><button class="btn" style="width:100%" type="submit">Create account</button></div>
{err}<p style="margin-top:12px"><a href="/login">Back to sign in</a></p></form>''')


def _create_owner(username: str, password: str, confirm: str):
    """Shared signup rules. Returns (username, None) or (None, error)."""
    if not _signup_open():
        return None, "This hub already has an owner account"
    username = (username or "").strip()
    if not (3 <= len(username) <= 32) or not username.replace("_", "").isalnum():
        return None, "Username must be 3–32 letters/digits/underscores"
    if len(password or "") < 8:
        return None, "Password must be at least 8 characters"
    if password != confirm:
        return None, "Passwords do not match"
    if store.get_user(username):
        return None, "That username is taken"
    store.create_user(username, password, role="owner")
    # lock the seeded default admin if it still carries the default password —
    # the owner account is now the only way in
    if username != settings.username and store.authenticate(settings.username, settings.password):
        store.set_password(settings.username, secrets.token_urlsafe(24))
    return username, None


@app.post("/signup")
def signup(username: str = Form(...), password: str = Form(...), confirm: str = Form(...)):
    user, err = _create_owner(username, password, confirm)
    if err:
        return RedirectResponse(f"/signup?error={err.replace(' ', '+')}", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, _sign_session(user), **_cookie_kwargs())
    return resp


@app.post("/logout")
def logout(request: Request):
    _sessions.pop(request.cookies.get(COOKIE, ""), None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ------------------------------------------------------------- auth JSON API
@app.get("/auth/status")
def auth_status(request: Request):
    """For the React app: who am I, and is first-time signup still open?"""
    u = _user(request)
    return {"authenticated": bool(u), "user": u, "signup_open": _signup_open()}


@app.post("/auth/logout")
def auth_logout(request: Request):
    _sessions.pop(request.cookies.get(COOKIE, ""), None)
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


# ------------------------------------------------- persistent user workspace
# Per-user settings blobs (namespace -> JSON), session-authenticated and
# strictly isolated by username. The backend DB is the source of truth; the
# frontends use localStorage only as a fast-boot cache. Nothing here is ever
# reset implicitly — DELETE is wired only to the user's explicit Reset actions.
_SETTINGS_NAMESPACES = ("settings-center", "dashboard", "preferences")


@app.get("/user/settings")
async def user_settings_get(request: Request, ns: str = "settings-center"):
    from fastapi.responses import JSONResponse
    u = _user(request)
    if not u:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    if ns not in _SETTINGS_NAMESPACES:
        return JSONResponse({"error": f"Unknown namespace {ns!r}"}, status_code=400)
    return {"ns": ns, "data": store.get_user_settings(u, ns)}


@app.post("/user/settings")
async def user_settings_set(request: Request):
    from fastapi.responses import JSONResponse
    u = _user(request)
    if not u:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    body = await request.json()
    ns = str(body.get("ns", "settings-center"))
    data = body.get("data")
    if ns not in _SETTINGS_NAMESPACES:
        return JSONResponse({"error": f"Unknown namespace {ns!r}"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "data must be an object"}, status_code=400)
    if len(str(data)) > 200_000:
        return JSONResponse({"error": "settings blob too large"}, status_code=413)
    store.set_user_settings(u, ns, data)
    return {"saved": True, "ns": ns}


@app.delete("/user/settings")
async def user_settings_reset(request: Request, ns: str = ""):
    """Explicit reset only (Reset Settings / Reset Dashboard / Factory Reset)."""
    from fastapi.responses import JSONResponse
    u = _user(request)
    if not u:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    if ns and ns not in _SETTINGS_NAMESPACES:
        return JSONResponse({"error": f"Unknown namespace {ns!r}"}, status_code=400)
    store.delete_user_settings(u, ns or None)
    return {"reset": True, "ns": ns or "all"}


@app.post("/auth/change-password")
async def auth_change_password(request: Request):
    u = _user(request)
    from fastapi.responses import JSONResponse
    if not u:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    body = await request.json()
    current, new = str(body.get("current", "")), str(body.get("new", ""))
    if store.authenticate(u, current) is None:
        return JSONResponse({"error": "Current password is wrong"}, status_code=400)
    if len(new) < 8:
        return JSONResponse({"error": "New password must be at least 8 characters"}, status_code=400)
    if hasattr(store, "set_password"):
        store.set_password(u, new)
        return {"ok": True, "note": "Password changed."}
    return JSONResponse({"error": "Password change not supported by this store"}, status_code=500)


# ------------------------------------------------------------------- dashboard
@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    # With the landing bundled, "/" is the PUBLIC marketing front door (it carries
    # no control secret). The dashboard lives at "/app" and stays sign-in gated.
    if _LANDING_READY:
        return _serve_landing(request)
    # ALL dashboards require sign-in — the served page carries the control
    # secret, so an anonymous visitor must never receive it.
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    if _WEBUI_READY:
        return _serve_react()
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
            f"<td>{w.state_badge(b.runtime.state.value)}</td>"
            f'<td class="rowbtns">'
            f'<a class="btn btn-ghost" href="/bots/{b.id}/backtest">Backtest</a>'
            f'<a class="btn btn-ghost" href="/bots/{b.id}/edit">Edit</a></td></tr>'
            for b in bots
        )
        table = (f'<div class="card"><table><thead><tr><th>Name</th><th>Strategy</th>'
                 f'<th>Exchange</th><th>Symbol</th><th>Mode</th><th>State</th>'
                 f'<th></th></tr></thead>'
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


# ----------------------------------------------------------- edit (Phase 9)
@app.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
def edit_bot_form(bot_id: str, request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    bot = manager.get(bot_id)
    if bot is None:
        return RedirectResponse("/bots", status_code=303)
    c, r = bot.config, bot.config.risk
    strat_opts = "".join(
        f'<option value="{k}"{" selected" if k == c.strategy else ""}'
        f'{"" if ready else " disabled"}>{w.esc(label)}</option>'
        for k, (_cls, label, ready) in STRATEGIES.items()
    )
    tf_opts = "".join(
        f'<option{" selected" if tf == c.timeframe else ""}>{tf}</option>'
        for tf in ("5m", "15m", "1h"))
    form = f'''<div class="card"><form method="post" action="/bots/{bot_id}/edit">
<div class="formgrid">
<div><label>Bot name</label><input name="name" value="{w.esc(c.name)}" required></div>
<div><label>Symbol</label><input name="symbol" value="{w.esc(c.symbol)}"></div>
<div><label>Strategy</label><select name="strategy">{strat_opts}</select></div>
<div><label>Timeframe</label><select name="timeframe">{tf_opts}</select></div>
<div><label>Risk per trade (%)</label><input name="risk_per_trade" type="number" step="0.1" value="{r.risk_per_trade_pct*100:.2f}"></div>
<div><label>Max daily loss (%)</label><input name="max_daily_loss" type="number" step="0.1" value="{r.max_daily_loss_pct*100:.2f}"></div>
<div><label>Max drawdown (%)</label><input name="max_drawdown" type="number" step="0.1" value="{r.max_drawdown_pct*100:.2f}"></div>
<div><label>Max consecutive losses</label><input name="max_consecutive_losses" type="number" value="{r.max_consecutive_losses}"></div>
</div><div style="margin-top:16px"><button class="btn" type="submit">Save Changes</button>
<a class="btn btn-ghost" href="/bots" style="margin-left:8px">Cancel</a></div></form></div>'''
    return HTMLResponse(w.page(title="Edit Bot", active="bots",
                               body=w.topbar(f"Edit · {w.esc(c.name)}") + form,
                               app_name=settings.app_name, user=u))


@app.post("/bots/{bot_id}/edit")
def edit_bot(
    bot_id: str,
    request: Request,
    name: str = Form(...),
    strategy: str = Form("ema"),
    symbol: str = Form("BTCUSDT"),
    timeframe: str = Form("1h"),
    risk_per_trade: float = Form(1.0),
    max_daily_loss: float = Form(3.0),
    max_drawdown: float = Form(20.0),
    max_consecutive_losses: int = Form(4),
):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    rules = RiskRules(
        risk_per_trade_pct=max(risk_per_trade, 0.01) / 100.0,
        max_daily_loss_pct=max(max_daily_loss, 0.1) / 100.0,
        max_open_positions=settings.max_open_positions,
        max_drawdown_pct=max(max_drawdown, 0.1) / 100.0,
        max_consecutive_losses=max(int(max_consecutive_losses), 0),
    )
    try:
        manager.update(bot_id, name=name, strategy=strategy, symbol=symbol,
                       timeframe=timeframe, risk=rules)
    except Exception as e:  # noqa: BLE001 — M-8: surface, don't swallow
        webhook_api.ledger.log(level="error", stage="bots",
                               message=f"edit_bot {bot_id} failed: {type(e).__name__}: {e}")
        from urllib.parse import quote
        return RedirectResponse(f"/bots?error={quote(f'Could not save bot: {e}')}", status_code=303)
    return RedirectResponse("/bots", status_code=303)


# ------------------------------------------------------- backtest (Phase 9)
@app.get("/bots/{bot_id}/backtest", response_class=HTMLResponse)
def backtest_bot(bot_id: str, request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    bot = manager.get(bot_id)
    if bot is None:
        return RedirectResponse("/bots", status_code=303)
    from dashboard.analytics import render_result
    res = manager.backtest(bot_id)
    head = (f'<div class="card"><h2>Backtest — {w.esc(bot.config.name)}</h2>'
            f'<div class="dim">{w.esc(bot.config.strategy.upper())} · '
            f'{w.esc(bot.config.symbol)} · {w.esc(bot.config.timeframe)} · '
            f'{w.esc(res.source)} data</div></div>')
    body = (w.topbar(f"Backtest · {w.esc(bot.config.name)}",
                     '<a class="btn btn-ghost" href="/bots">← Bots</a>')
            + head + render_result(bot.config.name, res.metrics, res.trades, res.equity_curve))
    return HTMLResponse(w.page(title="Backtest", active="bots", body=body,
                               app_name=settings.app_name, user=u))


def _bot_action(request: Request, action):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    try:
        action()
    except Exception as e:  # noqa: BLE001 — M-8: surface, don't swallow
        webhook_api.ledger.log(level="error", stage="bots",
                               message=f"bot action failed: {type(e).__name__}: {e}")
        from urllib.parse import quote
        return RedirectResponse(f"/?error={quote(f'Action failed: {e}')}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/bots/{bot_id}/start")
def start_bot(bot_id: str, request: Request):
    return _bot_action(request, lambda: manager.start(bot_id))


@app.post("/bots/{bot_id}/go-live")
def go_live_bot(bot_id: str, request: Request):
    # Phase 2: stream bars through the live engine (replay-driven demo).
    # Phase 8: forward the runner's events to the hub for the live dashboard.
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    bot = manager.get(bot_id)
    if bot is None:
        return RedirectResponse("/", status_code=303)
    name = bot.config.name

    def sink(event: dict, _bid: str = bot_id, _bn: str = name) -> None:
        hub_events.publish({**event, "bot_id": _bid, "bot_name": _bn})

    try:
        # Subscribe the sink before the worker starts (no missed events).
        manager.start_live(bot_id, event_sink=sink)
        hub_events.publish({"type": "lifecycle", "bot_id": bot_id,
                            "bot_name": name, "message": "went live"})
    except Exception as e:  # noqa: BLE001 — M-8: surface, don't swallow
        webhook_api.ledger.log(level="error", stage="bots",
                               message=f"go_live {bot_id} failed: {type(e).__name__}: {e}")
        from urllib.parse import quote
        return RedirectResponse(f"/?error={quote(f'Could not go live: {e}')}", status_code=303)
    return RedirectResponse("/", status_code=303)


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
    """Live paper account driven by the TradingView webhook -> paper engine.

    KPIs + emergency controls + open positions + closed-trade history, all read
    from the Kyros ledger (the source of truth)."""
    paper, controls = webhook_api.paper, webhook_api.controls
    cur = settings.currency
    realized = paper.realized_pnl()
    positions = paper.positions()
    history = paper.history()

    kpis = ('<div class="kpis">'
            + w.kpi("Balance", f"{cur}{paper.balance():,.2f}")
            + w.kpi("Realized P&L", f"{cur}{realized:,.2f}",
                    "pos" if realized >= 0 else "neg")
            + w.kpi("Open Positions", str(len(positions)))
            + w.kpi("Trading State", w.state_badge(controls.state))
            + '</div>')

    # Emergency controls (paper mode) — session-gated POSTs operate the same
    # control switch the webhook pipeline consults before every entry.
    controls_card = (
        '<div class="card"><h2>Emergency Controls</h2>'
        '<div class="rowbtns" style="justify-content:flex-start;gap:8px">'
        '<form class="inline" method="post" action="/paper-trading/pause">'
        '<button class="btn btn-warn" type="submit">⏸ Pause All</button></form>'
        '<form class="inline" method="post" action="/paper-trading/stop">'
        '<button class="btn btn-danger" type="submit">■ Stop All</button></form>'
        '<form class="inline" method="post" action="/paper-trading/resume">'
        '<button class="btn" type="submit">▶ Resume Trading</button></form>'
        '</div>'
        f'<p class="dim" style="margin-top:10px">Current state: '
        f'<b>{w.esc(controls.state)}</b>. Pause/Stop block new webhook entries; '
        'open positions still close on exit signals. Paper mode only.</p></div>')

    if positions:
        prows = "".join(
            f"<tr><td><b>{w.esc(p['symbol'])}</b></td>"
            f"<td>{w.esc(str(p['side']).title())}</td>"
            f"<td>{p['size']:.6f}</td><td>{cur}{p['entry']:,.2f}</td>"
            f"<td>{(cur + format(p['stop'], ',.2f')) if p.get('stop') else '—'}</td></tr>"
            for p in positions
        )
        pos_card = (f'<div class="card"><h2>Open Positions</h2><table><thead><tr>'
                    f'<th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th>'
                    f'<th>Stop</th></tr></thead><tbody>{prows}</tbody></table></div>')
    else:
        pos_card = ('<div class="card"><h2>Open Positions</h2>'
                    '<div class="empty">No open positions. Send a TradingView '
                    'webhook to <code>/webhook/tradingview</code> to open one.</div></div>')

    if history:
        hrows = "".join(
            f"<tr><td><b>{w.esc(t['symbol'])}</b></td>"
            f"<td>{w.esc(str(t['side']).title())}</td>"
            f"<td>{cur}{t['entry']:,.2f}</td>"
            f"<td>{cur}{(t.get('exit') or 0):,.2f}</td>"
            f"<td class='{'pos' if (t.get('pnl') or 0)>=0 else 'neg'}'>"
            f"{cur}{(t.get('pnl') or 0):,.2f}</td>"
            f"<td>{(t.get('rr') if t.get('rr') is not None else 0):.2f}R</td></tr>"
            for t in history
        )
        hist_card = (f'<div class="card"><h2>Trade History</h2><table><thead><tr>'
                     f'<th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th>'
                     f'<th>P&L</th><th>R:R</th></tr></thead>'
                     f'<tbody>{hrows}</tbody></table></div>')
    else:
        hist_card = ('<div class="card"><h2>Trade History</h2>'
                     '<div class="empty">No closed trades yet.</div></div>')

    return _simple_page(request, "Paper Trading", "paper",
                        kpis + controls_card + pos_card + hist_card)


# --------------------------------------------- emergency controls (UI, session-gated)
def _control_action(request: Request, action, level: str, message: str):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    action()
    webhook_api.ledger.log(level=level, stage="controls", message=message)
    return RedirectResponse("/paper-trading", status_code=303)


@app.post("/paper-trading/pause")
def ui_pause_all(request: Request):
    return _control_action(request, webhook_api.controls.pause_all,
                           "warning", "PAUSE ALL — entries blocked (dashboard)")


@app.post("/paper-trading/stop")
def ui_stop_all(request: Request):
    return _control_action(request, webhook_api.controls.stop_all,
                           "warning", "STOP ALL — trading halted (dashboard)")


@app.post("/paper-trading/resume")
def ui_resume(request: Request):
    return _control_action(request, webhook_api.controls.resume,
                           "info", "RESUME — trading active (dashboard)")


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


def _level_badge(level: str) -> str:
    cls = {"error": "b-err", "warning": "b-pause", "info": "b-paper"}.get(
        str(level).lower(), "b-new")
    return f'<span class="badge {cls}">{w.esc(str(level).upper())}</span>'


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    # Decision log from the ledger: every pipeline stage (controls/dedup/risk/
    # sizing/execution) records why a webhook signal executed or was rejected.
    decisions = webhook_api.ledger.get_logs(200)
    if decisions:
        drows = "".join(
            f"<tr><td class='dim'>{w.esc((d.get('ts') or '')[:19].replace('T',' '))}</td>"
            f"<td>{_level_badge(d.get('level'))}</td>"
            f"<td>{w.esc(d.get('stage') or '')}</td>"
            f"<td>{w.esc(d.get('symbol') or '')}</td>"
            f"<td>{w.esc(d.get('message') or '')}</td></tr>"
            for d in decisions
        )
        decision_card = (f'<div class="card"><h2>Decision Log</h2><table><thead><tr>'
                         f'<th>Time</th><th>Level</th><th>Stage</th><th>Symbol</th>'
                         f'<th>Message</th></tr></thead><tbody>{drows}</tbody></table></div>')
    else:
        decision_card = ('<div class="card"><h2>Decision Log</h2>'
                         '<div class="empty">No webhook decisions yet. Signals sent to '
                         '<code>/webhook/tradingview</code> appear here with their outcome.</div></div>')

    # Engine runtime events (backtest/live runner) — kept as a secondary feed.
    lines = []
    for b in manager.list():
        for ev in b.runtime.events[-40:]:
            lines.append(f"[{b.config.name}] {ev.get('type')} "
                         f"{ev.get('symbol','')} {ev.get('reason','')}".strip())
    engine_card = ('<div class="card"><h2>Engine Events</h2>'
                   + ('<pre style="white-space:pre-wrap;color:#9fb0c0">'
                      + w.esc("\n".join(lines[-200:])) + '</pre>'
                      if lines else '<div class="empty">No engine events yet.</div>')
                   + '</div>')
    return _simple_page(request, "Logs", "logs", decision_card + engine_card)


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request):
    alerts = webhook_api.ledger.get_alerts(100)
    if alerts:
        rows = "".join(
            f"<tr><td class='dim'>{w.esc((a.get('ts') or '')[:19].replace('T',' '))}</td>"
            f"<td>{_level_badge(a.get('severity'))}</td>"
            f"<td>{w.esc(a.get('category') or '')}</td>"
            f"<td><b>{w.esc(a.get('title') or '')}</b></td>"
            f"<td class='dim'>{w.esc(a.get('detail') or '')}</td></tr>"
            for a in alerts
        )
        inner = (f'<div class="card"><h2>Alerts</h2><table><thead><tr><th>Time</th>'
                 f'<th>Severity</th><th>Category</th><th>Title</th><th>Detail</th>'
                 f'</tr></thead><tbody>{rows}</tbody></table></div>')
    else:
        inner = ('<div class="card"><h2>Alerts</h2>'
                 '<div class="empty">No alerts yet. Trade executions, rejections and '
                 'risk events raise alerts here.</div></div>')
    return _simple_page(request, "Alerts", "alerts", inner)


@app.get("/live-trading", response_class=HTMLResponse)
def live_page(request: Request):
    from database.models import BotState
    bots = manager.list()
    cur = settings.currency
    live = [b for b in bots if b.runtime.state in (BotState.RUNNING, BotState.PAPER)]
    total_pnl = sum(b.runtime.pnl_today for b in bots)

    if bots:
        rows = "".join(
            f"<tr><td><b>{w.esc(b.config.name)}</b></td>"
            f"<td>{w.esc(exchange_label(b.config.exchange))}</td>"
            f"<td>{w.esc(b.config.symbol)}</td>"
            f"<td>{w.state_badge(b.runtime.state.value)}</td>"
            f"<td>{b.runtime.metrics.get('num_trades',0)}</td>"
            f"<td class='{'pos' if b.runtime.pnl_today>=0 else 'neg'}'>"
            f"{cur}{b.runtime.pnl_today:,.2f}</td></tr>"
            for b in bots
        )
        table = (f'<div class="card"><h2>Supervised Bots</h2><table><thead><tr>'
                 f'<th>Bot</th><th>Exchange</th><th>Symbol</th><th>State</th>'
                 f'<th>Trades</th><th>P&L today</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>'
                 '<form class="inline" method="post" action="/emergency-stop" style="margin-top:10px">'
                 '<button class="btn btn-danger" type="submit">■ Stop All Bots</button></form></div>')
    else:
        table = ('<div class="card"><div class="empty">No bots. Create one, then '
                 '“Go Live”.</div></div>')

    kpis = ('<div class="kpis">'
            + w.kpi("Live / Active", str(len(live)))
            + w.kpi("Total bots", str(len(bots)))
            + w.kpi("Aggregate P&L today", f"{cur}{total_pnl:,.2f}",
                    "pos" if total_pnl >= 0 else "neg")
            + w.kpi("Order routing", "dry-run (paper)")
            + '</div>')

    note = ('<div class="card"><h2>Real Order Routing</h2>'
            '<p class="dim">Set venue API keys (env / .env) and the runner mirrors each '
            'engine order to the exchange via execution/live_bridge.py as a bracket order; '
            'AlertDispatcher fires Telegram/Discord/email on fills, halts and completion. '
            'Defaults to dry-run until keys are supplied.</p></div>')
    return _simple_page(request, "Live Trading", "live", kpis + table + note)


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
    # The bundled landing owns the full Settings Center at /settings/*.
    if _LANDING_READY:
        return _serve_landing(request)
    u = _user(request)
    me = store.get_user(u) if u else None
    role = me.role if me else "operator"
    inner = (f'<div class="card"><h2>Settings</h2>'
             f'<div>Signed in as: <b>{w.esc(u or "")}</b> '
             f'<span class="dim">({w.esc(role)})</span></div>'
             f'<div>Default exchange: <b>{w.esc(settings.default_exchange)}</b></div>'
             f'<div>Currency: <b>{w.esc(settings.currency)}</b></div>'
             f'<div>Starting cash: <b>{settings.currency}{settings.starting_cash:,.0f}</b></div>'
             '<p class="dim" style="margin-top:10px">Passwords are hashed (PBKDF2). '
             'Manage accounts under <a class="pos" href="/users">Users</a>.</p></div>')
    return _simple_page(request, "Settings", "settings", inner)


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, error: str = ""):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    me = store.get_user(u)
    rows = "".join(
        f"<tr><td><b>{w.esc(x.username)}</b></td>"
        f"<td>{w.state_badge('Running' if x.role == 'admin' else 'Created')}</td>"
        f"<td>{w.esc(x.role)}</td>"
        f"<td class='dim'>{w.esc(x.created_at.strftime('%Y-%m-%d'))}</td></tr>"
        for x in store.list_users()
    )
    table = (f'<div class="card"><h2>Users</h2><table><thead><tr><th>Username</th>'
             f'<th></th><th>Role</th><th>Created</th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')
    if me and me.is_admin:
        err = f'<div class="err">{w.esc(error)}</div>' if error else ""
        form = ('<div class="card"><h2>Add User</h2>'
                '<form method="post" action="/users"><div class="formgrid">'
                '<div><label>Username</label><input name="username" required></div>'
                '<div><label>Password</label><input name="password" type="password" required></div>'
                '<div><label>Role</label><select name="role">'
                '<option value="operator">operator</option>'
                '<option value="admin">admin</option></select></div>'
                '</div><div style="margin-top:12px">'
                '<button class="btn" type="submit">Create User</button></div>'
                f'{err}</form></div>')
    else:
        form = '<div class="card"><div class="dim">Only admins can add users.</div></div>'
    return _simple_page(request, "Users", "settings", table + form)


@app.post("/users")
def create_user(request: Request, username: str = Form(...),
                password: str = Form(...), role: str = Form("operator")):
    u = _user(request)
    if not u:
        return RedirectResponse("/login", status_code=303)
    me = store.get_user(u)
    if not (me and me.is_admin):
        return RedirectResponse("/users?error=Admin+only", status_code=303)
    if store.get_user(username) is not None:
        return RedirectResponse("/users?error=User+already+exists", status_code=303)
    store.create_user(username, password, role="admin" if role == "admin" else "operator")
    return RedirectResponse("/users", status_code=303)


# --------------------------------------------------- live event stream (P8)
@app.get("/events/state")
def events_state(request: Request):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    return {"events": hub_events.replay()}


@app.get("/events/stream")
def events_stream(request: Request):
    if not _user(request):
        return RedirectResponse("/login", status_code=303)
    q = hub_events.subscribe()

    def gen():
        try:
            for ev in hub_events.replay():
                yield sse_format(ev)
            while True:
                try:
                    yield sse_format(q.get(timeout=15))
                except queue.Empty:
                    yield ": ping\n\n"      # heartbeat keeps proxies open
        finally:
            hub_events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _deploy_info() -> dict:
    """What version is actually deployed — from the env vars Render/host inject
    at build time, so you can confirm which commit is live without the dashboard.
    Empty strings when running locally (no CI env)."""
    import os
    commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT", "")
    return {
        "commit": commit,
        "commit_short": commit[:7],
        "branch": os.environ.get("RENDER_GIT_BRANCH") or os.environ.get("GIT_BRANCH", ""),
        "service": os.environ.get("RENDER_SERVICE_NAME", ""),
        "deployed_at": os.environ.get("RENDER_DEPLOY_ID", ""),
    }


def _persistence_info() -> dict:
    """Whether durable storage actually works — the honest answer to 'why do my
    settings reset?'. Both must be connected for settings + account to survive a
    free-tier redeploy."""
    try:
        from data.settings_store import SETTINGS_MIRROR_STATUS
        from data import ledger as _led
        return {
            "settings_supabase": {"configured": SETTINGS_MIRROR_STATUS["configured"],
                                  "connected": SETTINGS_MIRROR_STATUS["connected"],
                                  "error": SETTINGS_MIRROR_STATUS["error"]},
            "ledger_supabase": {"configured": _led.SUPABASE_STATUS.get("configured"),
                                "connected": _led.SUPABASE_STATUS.get("connected"),
                                "error": _led.SUPABASE_STATUS.get("error")},
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, **_deploy_info(),
            "persistence": _persistence_info()}


@app.get("/version")
def version():
    """The deployed build's commit/branch — match commit_short to `git log`."""
    return {"app": settings.app_name, **_deploy_info()}
