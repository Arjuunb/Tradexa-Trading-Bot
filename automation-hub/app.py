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
from fastapi import FastAPI, Form, HTTPException, Request  # noqa: E402
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

# The API version prefix, declared before the app so the OpenAPI docs can live
# under it (see below). The router mount further down reuses this constant.
API_VERSION = "v1"

# Swagger and ReDoc move under /api/v1 rather than sitting at the root.
#
# FastAPI serves them at "/docs" and "/redoc" by default, and "/docs" is now a
# page of the public marketing site — the documentation index. The built-in
# routes are registered at construction, so they win every match and the public
# page was simply unreachable in the bundled deployment. Moving them is also
# what docs/API_SPEC.md already prescribes for the versioned API surface.
app = FastAPI(
    title=settings.app_name,
    docs_url=f"/api/{API_VERSION}/docs",
    redoc_url=f"/api/{API_VERSION}/redoc",
)
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
    import sys as _sec_sys
    if settings.password == "admin":
        print("\n" + "=" * 68 + "\n  SECURITY WARNING: HUB_PASSWORD is the default 'admin'.\n"
              "  Set a strong HUB_PASSWORD before real use.\n" + "=" * 68 + "\n",
              file=_sec_sys.stderr, flush=True)
    if settings.webhook_secret == "dev-webhook-secret":
        # not a hard-fail (would lock a running deploy out of its own control
        # endpoints); a loud warning is the safe hardening here.
        print("\n" + "=" * 68 + "\n  SECURITY WARNING: HUB_WEBHOOK_SECRET is the default value.\n"
              "  Set HUB_WEBHOOK_SECRET (and HUB_API_KEY + HUB_SCOPE_WEBHOOK=1 to\n"
              "  decouple control from the TradingView secret) before real use.\n" + "=" * 68 + "\n",
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
# DSP Sprint 1c: expose the SAME JSON API under a versioned /api/v1 namespace,
# with the legacy root paths preserved (aliased) so nothing breaks. New clients
# target /api/v1; existing callers keep working unchanged. The auth/user
# endpoints defined directly on `app` stay at root for now (they move into a
# router in a later slice), so /api/v1 covers the router-based API surface.
app.include_router(webhook_router, prefix="/api/" + API_VERSION)


@app.get("/api/" + API_VERSION)
@app.get("/api/version")
def api_info():
    """Version handshake for the versioned API namespace."""
    return {"ok": True, "name": settings.app_name, "api_version": API_VERSION,
            "endpoints_base": "/api/" + API_VERSION, "legacy_base": "/"}

# The React dashboard runs on its own dev origin (Vite) and calls this API, so
# allow cross-origin during local development.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
# CORS origins are configurable: set HUB_CORS_ORIGINS to a comma-separated allow
# list (e.g. "https://www.trade-logx.com,https://x.onrender.com") in production.
# Unset defaults to "*" for local dev, but on a cloud host that is a loud warning
# (§10/§18 of the SAD) — credentials are off so the session cookie is never sent
# cross-origin, but tightening origins is still correct hygiene.
_cors_env = _sec_os.environ.get("HUB_CORS_ORIGINS", "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = ["*"]
    if _ON_CLOUD and not _UNDER_TEST:
        print("[cors] WARNING: HUB_CORS_ORIGINS unset — allowing all origins. "
              "Set it to your real origins in production.", flush=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins, allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# Iframe embedding (e.g. inside the Tradexa app): set HUB_FRAME_ANCESTORS to the
# embedding origin(s) — e.g. "https://tradexa.app" or "'self' https://tradexa.app"
# — and browsers will allow ONLY those sites to frame the dashboard (clickjacking
# stays blocked everywhere else). Unset = header not sent (default behavior).
import os as _mw_os  # noqa: E402


@app.middleware("http")
async def _security_headers(request, call_next):
    """Baseline security response headers (DSP Sprint 11). Deliberately does NOT
    set X-Frame-Options — framing is governed by the configurable CSP
    frame-ancestors below so the dashboard can still be embedded in the Tradexa
    app when HUB_FRAME_ANCESTORS is set."""
    resp = await call_next(request)
    # always-safe hardening
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # HSTS only on HTTPS (honours Render's X-Forwarded-Proto) — never on plain
    # HTTP, where browsers ignore it and it only risks dev confusion.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    # configurable framing policy (unchanged): opt-in embedding allow-list
    ancestors = _mw_os.environ.get("HUB_FRAME_ANCESTORS", "").strip()
    if ancestors:
        resp.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors}"
    return resp

# API protection: every data/control endpoint requires a signed-in session
# (cookie) or the webhook secret (header). Exempt: the auth flow itself, the
# TradingView webhook (it authenticates with the secret in its own handler),
# static assets, and "/" (which redirects anonymous visitors to /login).
_AUTH_EXEMPT = ("/login", "/signup", "/auth/", "/webhook", "/assets",
                "/favicon", "/openapi.json", "/health", "/version",
                "/api/v1/docs", "/api/v1/redoc",   # Swagger/ReDoc moved off "/docs"; same audience as before
                "/nexus-mark", "/apple-touch", "/icon-", "/maskable-", "/mstile-",
                "/og-image", "/logo-mark", "/site.webmanifest", "/robots.txt",
                "/sitemap.xml")

# The public marketing site's pages.
#
# Every one is a real URL in the sitemap, and the SPA uses BrowserRouter, so a
# hard load, a refresh or a crawler visit has to get HTML back from this app.
# Before these existed, eighteen of the nineteen returned this API's 404 JSON:
# client-side navigation worked, so the breakage was invisible to anyone
# already on the site and total for anyone arriving from a link or a search
# result — which is the entire audience the routes were split out for.
#
# Matched EXACTLY, never as prefixes. `_AUTH_EXEMPT` above is a prefix list,
# and exempting "/api" that way would have unlocked the whole "/api/v1/*"
# subtree that must stay session-gated.
_LANDING_PAGES = (
    "features", "engine", "live-trade", "selectivity", "how-it-works", "security",
    "performance", "dashboard", "docs", "api", "sdks", "open-source", "github",
    "support", "community", "status", "privacy", "terms", "risk-disclosure",
)
_LANDING_PAGE_PATHS = frozenset("/" + p for p in _LANDING_PAGES)


from services.ratelimit import limiter as _rl  # noqa: E402
# Per-IP sliding-window caps on the endpoints worth brute-forcing. Configurable;
# generous enough not to bite real users. Skipped under pytest.
_RL_AUTH = (int(_sec_os.environ.get("HUB_RL_AUTH_MAX", "12")), 300.0)      # login/signup: 12 / 5 min
_RL_WEBHOOK = (int(_sec_os.environ.get("HUB_RL_WEBHOOK_MAX", "120")), 60.0)  # webhook: 120 / min


def _client_ip(request: Request) -> str:
    """Real client IP behind Render's proxy (first X-Forwarded-For hop)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def _require_auth(request: Request, call_next):
    path = request.url.path
    # --- rate limiting (brute-force protection) — before auth so failed attempts
    # count. The under-test check is evaluated per-REQUEST (PYTEST_CURRENT_TEST is
    # set during a test's execution, not necessarily at import), so the limiter is
    # inert in the suite but live in production.
    if request.method == "POST" and not _sec_os.environ.get("PYTEST_CURRENT_TEST"):
        rule = None
        if path in ("/login", "/signup"):
            rule, tag = _RL_AUTH, "auth"
        elif path.startswith("/webhook"):
            rule, tag = _RL_WEBHOOK, "webhook"
        if rule is not None:
            limit, window = rule
            key = f"{_client_ip(request)}:{tag}"
            if not _rl.allow(key, limit, window):
                from fastapi.responses import JSONResponse
                ra = _rl.retry_after(key, window)
                return JSONResponse(
                    {"error": "Too many attempts. Please wait and try again."},
                    status_code=429, headers={"Retry-After": str(ra)})
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
    if (request.method == "OPTIONS"          # CORS preflight — CORSMiddleware answers it
            or path == "/" or path in ("/api/version", "/api/" + API_VERSION)  # public version handshake (NOT the /api/v1/* API subtree)
            # public marketing pages, matched exactly — see _LANDING_PAGE_PATHS
            or (_LANDING_READY and path in _LANDING_PAGE_PATHS)
            or any(path.startswith(p) for p in exempt)
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

# Root-level brand assets (favicons, PWA icons, OG image, manifest). Vite copies
# these from each app's public/ into its dist root, so they live beside index.html
# rather than under /assets. Serve them from whichever built app has them, plus a
# repo fallback so the backend-hosted pages (auth, legacy) always find the mark.
from fastapi.responses import FileResponse  # noqa: E402
_BRAND_FILES = ("nexus-mark.svg", "nexus-mark-small.svg", "favicon-16.png", "favicon-32.png", "favicon-48.png",
                "apple-touch-icon.png", "icon-192.png", "icon-512.png", "maskable-512.png",
                "mstile-150.png", "og-image.png", "logo-mark-512.png", "site.webmanifest",
                # Crawler files. They live beside index.html for the same reason
                # the icons do, and a sitemap that 404s is worse than none —
                # it advertises twenty URLs and then refuses to confirm any.
                "robots.txt", "sitemap.xml")
_BRAND_FALLBACK = Path(__file__).resolve().parent / "static" / "brand"


def _brand_asset(name: str):
    for base in (_LANDING, _WEBUI, _BRAND_FALLBACK):
        p = base / name
        if p.exists():
            return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="not found")


for _bf in _BRAND_FILES:
    app.add_api_route(f"/{_bf}", (lambda n: lambda: _brand_asset(n))(_bf),
                      methods=["GET"], include_in_schema=False)


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
    # Only the SPA shells that merely forward to the backend. The functional
    # flows — forgot/reset password, verify-email, two-factor — are served by
    # this app, because they need the users table and the session cookie. The
    # landing's versions of those pages were Supabase stubs against a second,
    # empty identity store; routing to them would authenticate nobody.
    _LANDING_AUTH = ("login", "register", "session-expired")

    def _landing_page(request: Request) -> HTMLResponse:
        return _serve_landing(request)

    def _landing_sub(request: Request, path: str = "") -> HTMLResponse:  # noqa: ARG001 — path is the SPA route
        return _serve_landing(request)

    for _p in _LANDING_AUTH:
        app.add_api_route(f"/auth/{_p}", _landing_page, response_class=HTMLResponse, methods=["GET"])
    app.add_api_route("/settings/{path:path}", _landing_sub, response_class=HTMLResponse, methods=["GET"])

    # Every public marketing page. Registered individually rather than behind a
    # catch-all: a catch-all would answer HTML to a mistyped API path, turning
    # a clear 404 into a parse error at the client, and would shadow nothing
    # today but everything added later.
    for _p in _LANDING_PAGES:
        app.add_api_route(f"/{_p}", _landing_page, response_class=HTMLResponse, methods=["GET"])

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
#: "Remember me" session length. 30 days is the common SaaS choice — long
#: enough to be the point of the tick box, short enough that a forgotten
#: session on a shared machine expires within a month.
REMEMBER_DAYS = 30


def _session_days(remember: bool) -> int:
    return REMEMBER_DAYS if remember else SESSION_DAYS


def _start_session(resp, username: str, request=None, *, remember: bool = False):
    """Issue a session cookie AND record the device it belongs to.

    The row is what makes the session revocable and listable; the cookie carries
    its id so the two are the same session. Recording is best-effort — a failure
    here must not turn a valid sign-in into a failed one, and the cookie alone
    still authenticates exactly as it did before this existed.
    """
    import uuid
    days = _session_days(remember)
    session_id = uuid.uuid4().hex
    try:
        store.create_session(
            username, session_id, ttl_days=days, remembered=remember,
            user_agent=(request.headers.get("user-agent", "") if request else ""),
            ip=((request.client.host if request and request.client else "") or ""))
        store.touch_login(username)
    except Exception:  # noqa: BLE001 — never block a login on bookkeeping
        session_id = ""
    from services.session_auth import sign
    token = sign(username, settings.secret_key, ttl_days=days,
                 session_id=session_id)
    resp.set_cookie(COOKIE, token, **_cookie_kwargs(days))
    return resp


def _cookie_kwargs(days: int = SESSION_DAYS) -> dict:
    """Session-cookie attributes. Default SameSite=Lax (same-origin dashboard).
    Set HUB_COOKIE_SAMESITE=none to allow the dashboard to be embedded in an
    iframe on another site (e.g. the Tradexa app) — SameSite=None requires
    Secure, so it only works over HTTPS (which Render provides)."""
    import os
    samesite = os.environ.get("HUB_COOKIE_SAMESITE", "lax").lower()
    if samesite not in ("lax", "none", "strict"):
        samesite = "lax"
    kw = {"httponly": True, "samesite": samesite,
          "max_age": int(days) * 86400}
    if samesite == "none":
        kw["secure"] = True
    return kw



def _wants_remember(form) -> bool:
    """Whether the sign-in form ticked "Remember me".

    Browsers submit a checked box as "on" and omit it entirely when unchecked,
    so presence is the signal; the value is only checked for explicit falsey
    strings a JSON client might send.
    """
    try:
        raw = form.get("remember") if form is not None else None
    except Exception:  # noqa: BLE001
        return False
    if raw is None:
        return False
    return str(raw).strip().lower() not in ("", "0", "false", "off", "no")


# --------------------------------------------------------------- auth helpers
def _sign_session(username: str) -> str:
    """Stateless signed session token (survives server restarts — important on
    hosts that spin down). The HMAC itself lives in services.session_auth so the
    API routers verify the same token with the same code, not a copy of it."""
    from services.session_auth import sign
    return sign(username, settings.secret_key, ttl_days=SESSION_DAYS)


def _verify_session(token: str):
    """Authentic + unexpired + still a real account. session_auth answers the
    first two; the user store answers the third."""
    from services.session_auth import split_session
    username, session_id = split_session(token, settings.secret_key)
    if not username:
        return None
    user = store.get_user(username)
    # A soft-deleted account holds a signature that is still cryptographically
    # valid. Authenticity is not authorisation: the token proves who issued it,
    # the store decides whether that account may still act.
    if not user or not getattr(user, "active", True):
        return None
    if session_id:
        # Only tokens that CARRY an id are checked against the table, so cookies
        # issued before the sessions migration keep working (see
        # store.session_is_valid).
        if not store.session_is_valid(session_id):
            return None
        store.touch_session(session_id)
    return username


# --------------------------------------------------------------- JWT (Sprint 1)
# A stateless JWT access token issued ALONGSIDE the signed session cookie. Same
# server-only secret (HUB_SECRET), same 7-day life for parity with the cookie
# (short-lived access + refresh rotation arrives with the sessions table). The
# cookie path is unchanged; a request may present either credential.
def issue_access(username: str) -> str:
    from services import jwt_tokens
    return jwt_tokens.encode({"sub": username, "typ": "access"},
                             settings.secret_key, ttl_seconds=SESSION_DAYS * 86400)


def verify_access(token: str):
    from services import jwt_tokens
    body = jwt_tokens.decode(token, settings.secret_key)
    if not body or body.get("typ") != "access":
        return None
    username = body.get("sub")
    return username if username and store.get_user(username) else None


def _bearer(request: Request):
    """Username from an `Authorization: Bearer <jwt>` header, if present + valid."""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return verify_access(auth[7:].strip())
    return None


def _user(request: Request):
    token = request.cookies.get(COOKIE, "")
    # cookie first (the browser dashboard), then a Bearer JWT (API clients),
    # then the legacy in-memory map kept only for test fixtures.
    return _verify_session(token) or _bearer(request) or _sessions.get(token)


def _require(request: Request):
    """Return username or a RedirectResponse to /login."""
    u = _user(request)
    return u if u else RedirectResponse("/login", status_code=303)


def _tenant(request: Request) -> str:
    """The data-tenant for this request (Phase C seam). Single-owner: always the
    owner. Multi-user (HUB_MULTI_USER): the signed-in user. Stores default to the
    owner, so this only diverges once multi-user is switched on."""
    from services.tenancy import resolve_tenant
    return resolve_tenant(_user(request))


def _request_role(request: Request):
    """The RBAC role for this request. A signed-in user's stored role; or
    'owner' when the caller presents the admin/control secret (automation acts
    with full authority); else None (anonymous)."""
    u = _user(request)
    if u:
        rec = store.get_user(u)
        if rec is not None:
            return rec.role
    # control-secret callers (admin key, or the webhook secret when it is NOT
    # scoped) act with full authority — mirror the auth wall's control check.
    hdr = request.headers.get("x-webhook-secret")
    if hdr and (hdr == settings.admin_key
                or (not settings.scope_webhook_secret and hdr == settings.webhook_secret)):
        return "owner"
    return None


def _has_role(request: Request, minimum: str) -> bool:
    """True if this request's role is at least ``minimum`` (rbac hierarchy)."""
    from services import rbac
    return rbac.role_at_least(_request_role(request), minimum)


def _require_role(request: Request, minimum: str):
    """Raise 403 unless the request's role is at least ``minimum``. For JSON
    endpoints; HTML pages branch on ``_has_role`` instead."""
    if not _has_role(request, minimum):
        raise HTTPException(status_code=403, detail="Insufficient role")


def _signup_open() -> bool:
    """Signup creates the single OWNER account. It stays open only while the
    seeded default admin is the sole user — after that this hub has an owner."""
    return all(u.username == settings.username for u in store.list_users())


# ----------------------------------------------------------------------- login
# TradeLogX Nexus brand mark — gold intelligence core, blue data links (matches
# the dashboard Logo component so both apps carry ONE brand).
_BRAND_MARK = ('<svg width="32" height="32" viewBox="0 0 96 96" fill="none" '
               'xmlns="http://www.w3.org/2000/svg" aria-label="TradeLogX Nexus">'
               '<defs>'
               '<linearGradient id="nxsA" x1="24" y1="0" x2="72" y2="0" gradientUnits="userSpaceOnUse">'
               '<stop offset="0" stop-color="#E9EEF3"/><stop offset=".46" stop-color="#AEB7C2"/>'
               '<stop offset=".54" stop-color="#E7C766"/><stop offset="1" stop-color="#C6961F"/></linearGradient>'
               '<linearGradient id="nxrA" x1="14" y1="14" x2="82" y2="82" gradientUnits="userSpaceOnUse">'
               '<stop stop-color="#E7C766"/><stop offset=".5" stop-color="#8A929C"/><stop offset="1" stop-color="#C6961F"/></linearGradient>'
               '</defs>'
               '<circle cx="48" cy="48" r="41" stroke="url(#nxrA)" stroke-width="2.6" opacity="0.85"/>'
               '<path d="M31 70 V32 M31 32 L65 70 M65 70 V26" stroke="url(#nxsA)" stroke-width="11" stroke-linecap="butt" stroke-linejoin="miter"/>'
               '<path d="M31 14 L40 30 H22 Z" fill="#E9EEF3"/>'
               '<path d="M65 82 L56 66 H74 Z" fill="#C6961F"/></svg>')
_BRAND_HEAD = (f'<div class="brand">{_BRAND_MARK}'
               '<span class="wordmark">TradeLogX <b>Nexus</b></span></div>')

# ---- inline icons (match the landing's lucide set) -------------------------
_IC_USER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
_IC_LOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
_IC_EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>'
_IC_TREND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 7 13.5 15.5 8.5 10.5 2 17"/><path d="M16 7h6v6"/></svg>'
_IC_SHIELD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>'
_IC_ZAP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z"/></svg>'

# demo equity line for the showcase (hand-drawn shape, clearly labelled demo)
_SC_CURVE = [10, 26, 20, 38, 33, 52, 48, 66, 62, 80]
_SC_PATH = " ".join(
    f'{"M" if i == 0 else "L"}{(i/(len(_SC_CURVE)-1))*260:.1f},{80-(v/100)*80:.1f}'
    for i, v in enumerate(_SC_CURVE))
_SHOWCASE = f'''<aside class="showcase">
  <div class="sc-top">
    <div class="eyebrow">TradeLogX Nexus</div>
    <h2 class="sc-title">Automated Trading.<br><span class="grad">Human Intelligence.</span></h2>
    <p class="sc-sub">Analyze markets, execute strategies, and manage risk — with complete transparency over every decision Nexus makes.</p>
  </div>
  <div class="sc-card">
    <div class="sc-card-h"><span>EQUITY · DEMO</span><span class="emer">+18.4%</span></div>
    <svg viewBox="0 0 260 80" preserveAspectRatio="none" class="sc-svg"><path d="{_SC_PATH}" pathLength="1" fill="none" stroke="#4FD98E" stroke-width="2" stroke-linecap="round" class="sc-line"/></svg>
  </div>
  <div class="sc-stats">
    <div class="sc-chip"><span class="sc-ic">{_IC_TREND}</span><div><b>Fully automated</b><span>Strategies executed</span></div></div>
    <div class="sc-chip"><span class="sc-ic">{_IC_SHIELD}</span><div><b>Encrypted · No withdrawals</b><span>Keys</span></div></div>
    <div class="sc-chip"><span class="sc-ic">{_IC_ZAP}</span><div><b>Sub-100ms routing</b><span>Execution</span></div></div>
  </div>
</aside>'''

# Full premium auth stylesheet — mirrors the landing's design tokens exactly
# (page-depth radial, warm grid, gold/emerald blooms, glass card, gold-sheen
# button, icon inputs). Self-contained; the legacy dashboard CSS is NOT loaded.
_AUTH_CSS = '''*{box-sizing:border-box}
:root{--gold:#C9A24B;--gold-soft:#E7CE86;--ink:#08080A;--line:rgba(255,255,255,.08)}
html,body{margin:0;min-height:100%}
body{background:#08080A;color:#fff;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
 -webkit-font-smoothing:antialiased;position:relative;overflow-x:hidden}
/* background layers (fixed) */
body::before,body::after{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none}
body::before{background:radial-gradient(120% 85% at 50% 0%,#0D0C0A 0%,#08080A 48%,#050506 100%)}
.bg{position:fixed;inset:0;z-index:-1;pointer-events:none;overflow:hidden}
.bg .grid{position:absolute;inset:0;
 background-image:linear-gradient(to right,rgba(226,214,182,.045) 1px,transparent 1px),linear-gradient(to bottom,rgba(226,214,182,.045) 1px,transparent 1px);
 background-size:28px 28px;-webkit-mask-image:linear-gradient(to bottom,#000 0%,#000 55%,transparent 100%);
 mask-image:linear-gradient(to bottom,#000 0%,#000 55%,transparent 100%);opacity:.6;animation:gridpan 8s linear infinite}
.bg .grid2{position:absolute;inset:0;background-image:linear-gradient(to right,rgba(226,214,182,.045) 1px,transparent 1px),linear-gradient(to bottom,rgba(226,214,182,.045) 1px,transparent 1px);background-size:140px 140px;opacity:.35;-webkit-mask-image:linear-gradient(to bottom,#000 0%,#000 55%,transparent 100%);mask-image:linear-gradient(to bottom,#000 0%,#000 55%,transparent 100%)}
.bg .bloom{position:absolute;border-radius:50%;filter:blur(130px)}
.bg .bloom-gold{top:-12rem;left:50%;width:46rem;height:34rem;transform:translateX(-50%);background:rgba(201,162,75,.05);animation:bloom 18s ease-in-out infinite}
.bg .bloom-emer{bottom:-14rem;right:-12rem;width:40rem;height:30rem;background:rgba(47,191,113,.05);filter:blur(150px)}
.bg .vig{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 58%,rgba(0,0,0,.6))}
@keyframes gridpan{from{background-position:0 0}to{background-position:28px 28px}}
@keyframes bloom{0%,100%{opacity:.75;transform:translateX(-50%) scale(1)}50%{opacity:1;transform:translateX(-50%) scale(1.06)}}
/* layout */
.auth{display:grid;grid-template-columns:1.05fr .95fr;min-height:100vh}
.topbar{position:absolute;top:0;right:0;padding:22px 26px;z-index:5}
.topbar a{color:rgba(255,255,255,.5);text-decoration:none;font-size:13.5px;display:inline-flex;align-items:center;gap:6px;transition:color .2s}
.topbar a:hover{color:#fff}
/* showcase (left) */
.showcase{position:relative;display:flex;flex-direction:column;justify-content:space-between;padding:56px;overflow:hidden;background:#0C0C0F;border-right:1px solid var(--line)}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.24em;text-transform:uppercase;color:var(--gold)}
.sc-title{font-size:40px;line-height:1.05;font-weight:800;letter-spacing:-.02em;margin:18px 0 0;max-width:11ch}
.sc-title .grad{background:linear-gradient(120deg,#E7D89A,#C8A94B 55%,#A98E3A);-webkit-background-clip:text;background-clip:text;color:transparent}
.sc-sub{margin:16px 0 0;max-width:34ch;font-size:14px;line-height:1.6;color:rgba(255,255,255,.55)}
.sc-card{background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:16px;padding:18px;backdrop-filter:blur(8px);box-shadow:0 20px 50px -20px rgba(0,0,0,.6)}
.sc-card-h{display:flex;justify-content:space-between;font-size:11px;letter-spacing:.08em;color:rgba(255,255,255,.4);margin-bottom:10px}
.sc-card-h .emer{color:#4FD98E;letter-spacing:0}
.sc-svg{width:100%;height:74px;display:block}
.sc-line{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.6s ease-in-out .4s forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.sc-stats{display:flex;flex-direction:column;gap:12px}
.sc-chip{display:flex;align-items:center;gap:12px;background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:12px;padding:12px 14px;opacity:0;transform:translateX(-16px);animation:slidein .5s ease forwards}
.sc-chip:nth-child(1){animation-delay:.35s}.sc-chip:nth-child(2){animation-delay:.47s}.sc-chip:nth-child(3){animation-delay:.59s}
.sc-ic{display:flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:9px;background:rgba(201,162,75,.1);color:var(--gold);flex:none}
.sc-ic svg{width:16px;height:16px}
.sc-chip b{display:block;font-size:13.5px;font-weight:600}
.sc-chip span{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:rgba(255,255,255,.4)}
@keyframes slidein{to{opacity:1;transform:translateX(0)}}
/* form (right) */
.formcol{display:flex;align-items:center;justify-content:center;padding:40px 24px}
.card{width:100%;max-width:400px;opacity:0;transform:translateY(20px) scale(.98);animation:rise .55s cubic-bezier(.22,1,.36,1) forwards}
@keyframes rise{to{opacity:1;transform:none}}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:26px}
.brand svg{width:34px;height:34px}
.wordmark{font-size:19px;font-weight:700;letter-spacing:-.01em;color:#eef1f5}
.wordmark b{color:var(--gold)}
.card h1{font-size:28px;font-weight:800;letter-spacing:-.02em;margin:0}
.card .sub{margin:8px 0 26px;font-size:14px;color:rgba(255,255,255,.5)}
.fld{display:block;margin-bottom:16px}
.fld .lbl{display:flex;justify-content:space-between;align-items:center;font-size:12.5px;font-weight:500;color:rgba(255,255,255,.75);margin-bottom:7px}
.fld .lbl a{color:var(--gold);opacity:.85;text-decoration:none;font-size:12px}
.fld .lbl a:hover{opacity:1}
.inp{display:flex;align-items:center;gap:10px;background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:12px;padding:0 12px;height:48px;transition:border-color .2s,box-shadow .2s,background .2s}
.inp:hover{background:rgba(255,255,255,.05)}
.inp:focus-within{border-color:var(--gold);background:rgba(201,162,75,.05);box-shadow:0 0 0 3px rgba(201,162,75,.18)}
.inp .ico{display:flex;color:rgba(255,255,255,.4);flex:none}
.inp .ico svg{width:17px;height:17px}
.inp input{flex:1;min-width:0;background:none;border:0;outline:0;color:#fff;font-size:14.5px;font-family:inherit;height:100%}
.inp input::placeholder{color:rgba(255,255,255,.3)}
.inp .eye{background:none;border:0;cursor:pointer;color:rgba(255,255,255,.4);display:flex;padding:4px;border-radius:6px}
.inp .eye:hover{color:#fff}
.inp .eye svg{width:17px;height:17px}
.btn-gold{position:relative;overflow:hidden;width:100%;height:50px;margin-top:6px;border:0;border-radius:12px;cursor:pointer;
 background:linear-gradient(135deg,#E7D89A 0%,#C8A94B 45%,#A98E3A 100%);color:#08080A;font-family:inherit;font-size:15px;font-weight:700;letter-spacing:.01em;
 box-shadow:0 10px 40px -12px rgba(200,169,75,.45);transition:filter .2s,transform .12s,box-shadow .2s;display:flex;align-items:center;justify-content:center;gap:8px}
.btn-gold:hover{filter:brightness(1.06);box-shadow:0 14px 46px -12px rgba(200,169,75,.6)}
.btn-gold:active{transform:translateY(1px) scale(.995);filter:brightness(.96)}
.btn-gold .sheen{position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);transition:transform .7s}
.btn-gold:hover .sheen{transform:translateX(100%)}
.btn-gold.loading{pointer-events:none;opacity:.85}
.btn-gold .spin{width:17px;height:17px;border:2px solid rgba(8,8,10,.35);border-top-color:#08080A;border-radius:50%;animation:spin .7s linear infinite;display:none}
.btn-gold.loading .spin{display:block}.btn-gold.loading .txt{opacity:.85}
@keyframes spin{to{transform:rotate(360deg)}}
.divider{display:flex;align-items:center;gap:12px;margin:22px 0;color:rgba(255,255,255,.35);font-size:12px}
.divider::before,.divider::after{content:"";height:1px;flex:1;background:var(--line)}
.foot{margin-top:26px;text-align:center;font-size:13.5px;color:rgba(255,255,255,.5)}
.foot a{color:var(--gold);font-weight:600;text-decoration:none}.foot a:hover{color:var(--gold-soft)}
.err{margin-top:14px;padding:11px 13px;border-radius:11px;font-size:13px;color:#F07E7A;background:rgba(229,96,91,.1);border:1px solid rgba(229,96,91,.3);animation:shake .4s}
@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}
.note{margin-top:18px;padding:11px 13px;border-radius:11px;font-size:12px;color:rgba(255,255,255,.6);background:rgba(201,162,75,.06);border:1px solid rgba(201,162,75,.2)}
@media (max-width:900px){.auth{grid-template-columns:1fr}.showcase{display:none}.formcol{padding:64px 20px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}'''

_AUTH_HEAD_LINKS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
    '<link rel="icon" type="image/svg+xml" href="/nexus-mark-small.svg">'
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">'
    '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">')

_AUTH_JS = ('<script>function tpw(b){var i=document.getElementById("pw");if(i){i.type=i.type==="password"?"text":"password";}}'
            'function tpw2(b){var i=document.getElementById("pw2");if(i){i.type=i.type==="password"?"text":"password";}}'
            'function subm(f){var b=f.querySelector(".btn-gold");if(b)b.classList.add("loading");return true;}</script>')


def _auth_page(title: str, body: str) -> str:
    """Premium auth shell — the landing's background + a glass card, self-contained."""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#08080A">
<title>{w.esc(title)} · TradeLogX Nexus</title>{_AUTH_HEAD_LINKS}
<style>{_AUTH_CSS}</style></head>
<body>
<div class="bg"><div class="grid"></div><div class="grid2"></div>
<div class="bloom bloom-gold"></div><div class="bloom bloom-emer"></div><div class="vig"></div></div>
<div class="topbar"><a href="/">← Back to site</a></div>
<div class="auth">{_SHOWCASE}<div class="formcol"><div class="card">{body}</div></div></div>
{_AUTH_JS}
</body></html>'''


def _pw_field(name: str, label: str, fid: str, toggle: str, autocomplete: str, hint: str = "") -> str:
    return (f'<label class="fld"><span class="lbl">{label}{hint}</span>'
            f'<div class="inp"><span class="ico">{_IC_LOCK}</span>'
            f'<input id="{fid}" name="{name}" type="password" autocomplete="{autocomplete}" placeholder="••••••••">'
            f'<button type="button" class="eye" onclick="{toggle}(this)" aria-label="Show password">{_IC_EYE}</button></div></label>')


from services import auth_flows as _af  # noqa: E402
from services import mailer as _mailer  # noqa: E402
from services import oauth as _oauth  # noqa: E402


def _q(text: str) -> str:
    """Percent-encode a message for a redirect query string. '+' for spaces is
    not enough — an apostrophe or an '&' in an error message would otherwise
    truncate it or split it into a second parameter."""
    from urllib.parse import quote_plus
    return quote_plus(text or "")


def _storage_notice() -> str:
    """Warn on the sign-in page itself when accounts do not survive a redeploy.

    This is where someone whose account was erased actually lands, and without
    it the only evidence is a boot log they cannot see. Silence here reads as
    "you typed it wrong".
    """
    try:
        if webhook_api.storage_assessment()["local_durable"]:
            return ""
    except Exception:  # noqa: BLE001 — never break the login page over a notice
        return ""
    return ('<div class="err">Accounts are stored on ephemeral disk and are '
            'erased on every redeploy. Set HUB_DATA_DIR to a mounted persistent '
            'disk to keep them, or sign in with HUB_USERNAME / HUB_PASSWORD, '
            'which are re-seeded from the environment on each boot.</div>')


@app.get("/login", response_class=HTMLResponse)
def login_form(error: str = "") -> str:
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    err += _storage_notice()
    signup = ('<p class="foot">New here? <a href="/signup">Create your account</a></p>'
              if _signup_open() else "")
    return _auth_page("Sign in", f'''{_BRAND_HEAD}
<h1>Welcome back</h1>
<p class="sub">Sign in to your TradeLogX Nexus workspace.</p>
<form method="post" action="/login" onsubmit="return subm(this)" novalidate>
<label class="fld"><span class="lbl">Username or email</span>
<div class="inp"><span class="ico">{_IC_USER}</span><input name="username" autocomplete="username" placeholder="you@email.com or a username" autofocus></div></label>
{_pw_field("password", "Password", "pw", "tpw", "current-password")}
<button class="btn-gold" type="submit"><span class="sheen"></span><span class="spin"></span><span class="txt">Sign in</span></button>
</form>
{err}{signup}''')


def _login_failure_message(username: str) -> str:
    """Why the sign-in failed, said in a way the person can act on.

    "Invalid credentials" is the right answer for a wrong password and the
    wrong answer for a missing account: it sends someone to re-check a password
    that was never the problem. This hub already discloses whether an owner
    exists (the signup link appears exactly when one does not), so naming a
    missing account leaks nothing new — and on ephemeral storage it is the
    difference between "retype it" and "your account was wiped by a redeploy".
    """
    if store.auth_failure_reason(username) == "bad-password":
        return "Invalid credentials"
    msg = "No account with that username or email exists on this hub"
    try:
        # webhook_api owns the one storage assessment (it knows the real
        # Supabase connection state); re-deriving it here would drift.
        if not webhook_api.storage_assessment()["local_durable"]:
            msg += (". Storage is ephemeral, so accounts are erased on every "
                    "redeploy — set HUB_DATA_DIR to a persistent disk to keep them")
    except Exception:  # noqa: BLE001 — a diagnosis must never break sign-in
        pass
    return msg


PENDING_2FA_COOKIE = "hub_2fa"
PENDING_2FA_TTL_S = 300          # 5 minutes to fetch a code off a phone


def _pending_2fa_token(username: str) -> str:
    """A ticket saying "this password was correct, the second factor is not
    done yet". Signed under a purpose-scoped key so it can NEVER be presented
    as a session cookie — otherwise the second factor would be skippable."""
    from services.session_auth import sign_scoped
    return sign_scoped(username, settings.secret_key, purpose="2fa-pending",
                       ttl_s=PENDING_2FA_TTL_S)


def _pending_2fa_user(request: Request) -> Optional[str]:
    from services.session_auth import verify_scoped
    name = verify_scoped(request.cookies.get(PENDING_2FA_COOKIE, ""),
                         settings.secret_key, purpose="2fa-pending")
    return name if name and store.get_user(name) else None


def _grant_session(user, destination: str = "/", request=None, *,
                   remember: bool = False):
    resp = RedirectResponse(destination, status_code=303)
    # Sign the STORED username, not the typed one — otherwise a case-variant
    # sign-in mints a session under a name whose per-user settings namespace
    # is empty.
    _start_session(resp, user.username, request, remember=remember)
    resp.delete_cookie(PENDING_2FA_COOKIE)
    return resp


@app.post("/login")
def login(request: Request, username: str = Form(...),
          password: str = Form(...), remember: str = Form("")):
    # verify against hashed credentials; signed cookie survives restarts
    user = store.authenticate(username, password)
    if user is not None:
        if user.totp_enabled:
            # A correct password is now only half the sign-in. Hand out the
            # pending ticket, not a session.
            resp = RedirectResponse("/auth/two-factor", status_code=303)
            kw = dict(_cookie_kwargs())
            kw["max_age"] = PENDING_2FA_TTL_S
            resp.set_cookie(PENDING_2FA_COOKIE, _pending_2fa_token(user.username), **kw)
            return resp
        return _grant_session(user, request=request,
                              remember=_wants_remember({"remember": remember}))
    err = _login_failure_message(username).replace(" ", "+")
    return RedirectResponse(f"/login?error={err}", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
def signup_form(error: str = "") -> str:
    if not _signup_open():
        return _auth_page("Sign up", f'''{_BRAND_HEAD}
<h1>Already set up</h1>
<p class="sub">This hub already has an owner account.</p>
<p class="foot"><a href="/login">Sign in instead →</a></p>''')
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    return _auth_page("Create account", f'''{_BRAND_HEAD}
<h1>Create your account</h1>
<p class="sub">Set up the owner account for your TradeLogX Nexus workspace.</p>
<form method="post" action="/signup" onsubmit="return subm(this)" novalidate>
<label class="fld"><span class="lbl">Username or email</span>
<div class="inp"><span class="ico">{_IC_USER}</span><input name="username" autocomplete="username" placeholder="you@email.com or a username" autofocus></div></label>
{_pw_field("password", "Password", "pw", "tpw", "new-password", hint="<span style='font-weight:400;color:rgba(255,255,255,.4)'>8+ characters</span>")}
{_pw_field("confirm", "Confirm password", "pw2", "tpw2", "new-password")}
<button class="btn-gold" type="submit"><span class="sheen"></span><span class="spin"></span><span class="txt">Create account</span></button>
</form>
{err}<p class="foot">Already have an account? <a href="/login">Sign in</a></p>''')


def _create_owner(username: str, password: str, confirm: str):
    """Shared signup rules. Returns (username, None) or (None, error)."""
    import re as _re
    if not _signup_open():
        return None, "This hub already has an owner account"
    username = (username or "").strip()
    # accept a plain username OR an email address (people naturally type their
    # email here — the field label offers both), letters/digits and . _ - + @
    if not (3 <= len(username) <= 64) or not _re.fullmatch(r"[A-Za-z0-9._+@-]+", username):
        return None, "Enter a username or email (3–64 chars: letters, digits, . _ - + @)"
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
def signup(request: Request, username: str = Form(...),
           password: str = Form(...), confirm: str = Form(...)):
    user, err = _create_owner(username, password, confirm)
    if err:
        return RedirectResponse(f"/signup?error={err.replace(' ', '+')}", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    _start_session(resp, user, request)
    return resp


@app.post("/logout")
def logout(request: Request):
    _sessions.pop(request.cookies.get(COOKIE, ""), None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ------------------------------------------------------------- auth JSON API
@app.post("/auth/login")
def auth_login(request: Request, username: str = Form(...),
               password: str = Form(...), remember: str = Form("")):
    """JSON login for API clients: returns a JWT access token AND sets the
    session cookie, so callers can use `Authorization: Bearer` while browsers
    keep the cookie. Same credential check as the form /login."""
    from fastapi.responses import JSONResponse
    user = store.authenticate(username, password)
    if user is None:
        raise HTTPException(status_code=401, detail=_login_failure_message(username))
    if user.totp_enabled:
        # No token yet — the caller must post the second factor to
        # /auth/two-factor with this ticket. Issuing the JWT here would make
        # 2FA cosmetic for every API client.
        resp = JSONResponse({"ok": False, "mfa_required": True,
                             "user": user.username,
                             "message": "Enter the code from your authenticator app."},
                            status_code=401)
        kw = dict(_cookie_kwargs())
        kw["max_age"] = PENDING_2FA_TTL_S
        resp.set_cookie(PENDING_2FA_COOKIE, _pending_2fa_token(user.username), **kw)
        return resp
    token = issue_access(user.username)
    resp = JSONResponse({"ok": True, "user": user.username, "token": token,
                         "token_type": "bearer", "expires_in": SESSION_DAYS * 86400})
    _start_session(resp, user.username, request,
                   remember=_wants_remember({"remember": remember} if remember else None))
    return resp


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
    resp.delete_cookie(PENDING_2FA_COOKIE)
    return resp


# ══════════════════════════════════════════════════ real auth flows
# Password reset, email verification, TOTP two-factor and OAuth sign-in, all
# against the SAME users table every other request is authorised against. The
# logic lives in services/auth_flows.py and services/oauth.py; these handlers
# are the HTTP skin over it.

def _msg_block(result: dict) -> str:
    """Render a flow result. A `delivery` block that is unavailable is an
    OPERATOR problem (no SMTP host, failed send) and is always shown — the
    user-facing sentence stays deliberately vague, but nobody should be left
    waiting for an email the server never attempted."""
    out = ""
    if result.get("error"):
        out += f'<div class="err">{w.esc(result["error"])}</div>'
    elif result.get("message"):
        out += f'<div class="ok">{w.esc(result["message"])}</div>'
    d = result.get("delivery") or {}
    if d and not d.get("available") and d.get("note"):
        out += f'<div class="err">{w.esc(d["note"])}</div>'
    return out


# ─────────────────────────────────────────────── forgot / reset password
@app.get("/auth/forgot-password", response_class=HTMLResponse)
def forgot_password_form(sent: str = "") -> str:
    note = ('<div class="ok">' + w.esc(_af.GENERIC_RESET_REPLY) + "</div>") if sent else ""
    delivery = _mailer.available()
    warn = ("" if delivery["available"]
            else f'<div class="err">{w.esc(delivery["note"])}</div>')
    return _auth_page("Reset password", f'''{_BRAND_HEAD}
<h1>Forgot your password?</h1>
<p class="sub">We'll email you a link to set a new one.</p>
<form method="post" action="/auth/forgot-password" onsubmit="return subm(this)" novalidate>
<label class="fld"><span class="lbl">Username or email</span>
<div class="inp"><span class="ico">{_IC_USER}</span><input name="identifier" autocomplete="username" placeholder="you@email.com or a username" autofocus></div></label>
<button class="btn-gold" type="submit"><span class="sheen"></span><span class="spin"></span><span class="txt">Send reset link</span></button>
</form>
{note}{warn}<p class="foot">Remembered it? <a href="/login">Sign in</a></p>''')


@app.post("/auth/forgot-password")
def forgot_password(identifier: str = Form(...)):
    result = _af.request_password_reset(store, identifier)
    # Always the same redirect, hit or miss: a different destination for a real
    # account would turn this form into a membership check.
    d = result.get("delivery") or {}
    if d and not d.get("available"):
        return RedirectResponse(
            "/auth/forgot-password?sent=1&error=" + _q(d.get("note", "")),
            status_code=303)
    return RedirectResponse("/auth/forgot-password?sent=1", status_code=303)


@app.get("/auth/reset-password", response_class=HTMLResponse)
def reset_password_form(token: str = "", error: str = "") -> str:
    if not token:
        return _auth_page("Reset password", f'''{_BRAND_HEAD}
<h1>Link missing</h1>
<p class="sub">Open the link from your email, or request a new one.</p>
<p class="foot"><a href="/auth/forgot-password">Send a new reset link</a></p>''')
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    return _auth_page("Reset password", f'''{_BRAND_HEAD}
<h1>Set a new password</h1>
<p class="sub">This link works once and expires an hour after it was sent.</p>
<form method="post" action="/auth/reset-password" onsubmit="return subm(this)" novalidate>
<input type="hidden" name="token" value="{w.esc(token)}">
{_pw_field("password", "New password", "np", "tnp", "new-password")}
{_pw_field("confirm", "Confirm password", "nc", "tnc", "new-password")}
<button class="btn-gold" type="submit"><span class="sheen"></span><span class="spin"></span><span class="txt">Update password</span></button>
</form>
{err}''')


@app.post("/auth/reset-password")
def reset_password(token: str = Form(...), password: str = Form(...),
                   confirm: str = Form("")):
    result = _af.perform_password_reset(store, token, password, confirm or None)
    if not result["ok"]:
        return RedirectResponse(
            f"/auth/reset-password?token={_q(token)}&error={_q(result['error'])}",
            status_code=303)
    # Deliberately NOT signed in here. Someone who reached this page from a
    # forwarded email should have to prove they know the new password.
    return RedirectResponse("/login?error=" + _q(result["message"]), status_code=303)


# ────────────────────────────────────────────────────── email verification
@app.get("/auth/verify-email", response_class=HTMLResponse)
def verify_email_page(request: Request, token: str = "") -> str:
    if token:
        result = _af.confirm_email(store, token)
        body = _msg_block(result)
        head = "Email confirmed" if result["ok"] else "That link didn't work"
        return _auth_page("Verify email", f'''{_BRAND_HEAD}
<h1>{head}</h1>{body}
<p class="foot"><a href="/login">Continue to sign in</a></p>''')
    u = _user(request)
    if not u:
        return _auth_page("Verify email", f'''{_BRAND_HEAD}
<h1>Confirm your email</h1>
<p class="sub">Open the link we emailed you.</p>
<p class="foot"><a href="/login">Sign in</a></p>''')
    return _auth_page("Verify email", f'''{_BRAND_HEAD}
<h1>Confirm your email</h1>
<p class="sub">Signed in as {w.esc(u)}. Send yourself a fresh confirmation link.</p>
<form method="post" action="/auth/resend-verification" onsubmit="return subm(this)">
<button class="btn-gold" type="submit"><span class="sheen"></span><span class="spin"></span><span class="txt">Send confirmation link</span></button>
</form>''')


@app.post("/auth/resend-verification")
def resend_verification(request: Request):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    return _af.request_email_verification(store, u)


# ────────────────────────────────────────────────────────────── two-factor
@app.get("/auth/two-factor", response_class=HTMLResponse)
def two_factor_page(request: Request, error: str = "") -> str:
    pending = _pending_2fa_user(request)
    if not pending:
        return _auth_page("Two-factor", f'''{_BRAND_HEAD}
<h1>Start again</h1>
<p class="sub">That sign-in expired. Enter your password again to get a fresh code prompt.</p>
<p class="foot"><a href="/login">Back to sign in</a></p>''')
    err = f'<div class="err">{w.esc(error)}</div>' if error else ""
    return _auth_page("Two-factor", f'''{_BRAND_HEAD}
<h1>Two-factor</h1>
<p class="sub">Enter the 6-digit code from your authenticator app, or a recovery code.</p>
<form method="post" action="/auth/two-factor" onsubmit="return subm(this)" novalidate>
<label class="fld"><span class="lbl">Code</span>
<div class="inp"><span class="ico">{_IC_LOCK}</span><input name="code" inputmode="text" autocomplete="one-time-code" placeholder="123456" autofocus></div></label>
<button class="btn-gold" type="submit"><span class="sheen"></span><span class="spin"></span><span class="txt">Verify</span></button>
</form>
{err}<p class="foot">Lost your phone? Use one of your recovery codes above.</p>''')


@app.post("/auth/two-factor")
def two_factor_submit(request: Request, code: str = Form(...)):
    pending = _pending_2fa_user(request)
    if not pending:
        return RedirectResponse("/login?error=" + _q("That sign-in expired. Try again."),
                                status_code=303)
    result = _af.verify_second_factor(store, pending, code)
    if not result["ok"]:
        return RedirectResponse("/auth/two-factor?error=" + _q(result["error"]),
                                status_code=303)
    return _grant_session(store.get_user(pending), request=request)


@app.get("/auth/2fa/status")
def two_factor_status(request: Request):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    return _af.totp_status(store, u)


@app.post("/auth/2fa/setup")
def two_factor_setup(request: Request):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    return _af.begin_totp_setup(store, u, issuer=settings.app_name)


@app.post("/auth/2fa/enable")
def two_factor_enable(request: Request, code: str = Form(...)):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    return _af.enable_totp(store, u, code)


@app.post("/auth/2fa/disable")
def two_factor_disable(request: Request, password: str = Form(...)):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    return _af.disable_totp(store, u, password)


# ──────────────────────────────────────────────────────────────── OAuth
@app.get("/auth/oauth/providers")
def oauth_providers():
    """What can actually complete a sign-in. The UI disables the rest WITH the
    reason, rather than showing a button that dies on click."""
    return _oauth.available()


@app.get("/auth/oauth/{provider}/start")
def oauth_start(provider: str):
    p = _oauth.get_provider(provider)
    if p is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not _oauth.is_configured(p) or not _mailer.public_url():
        raise HTTPException(status_code=503,
                            detail=_oauth.available()[p.key]["note"])
    state = _oauth.sign_state(settings.secret_key)
    return RedirectResponse(_oauth.authorize_url(p, state), status_code=303)


@app.post("/auth/oauth/{provider}/callback")
@app.get("/auth/oauth/{provider}/callback")
async def oauth_callback(request: Request, provider: str, code: str = "",
                         state: str = "", error: str = ""):
    # Apple posts the callback as a form (response_mode=form_post) when the
    # scope includes name or email; Google and GitHub use query parameters.
    # Reading the body only when the query is empty keeps the GET path
    # byte-identical to what it was.
    if request.method == "POST" and not code:
        try:
            form = await request.form()
            code = str(form.get("code") or "")
            state = str(form.get("state") or "")
            error = str(form.get("error") or "")
        except Exception:  # noqa: BLE001 — fall through to the "no code" branch
            pass
    p = _oauth.get_provider(provider)
    if p is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if error:
        return RedirectResponse("/login?error=" + _q(f"{p.label} sign-in was cancelled."),
                                status_code=303)
    # The state check comes before anything else touches the code: it is what
    # stops an attacker from having a victim's browser redeem a code they chose.
    if not _oauth.verify_state(state, settings.secret_key):
        return RedirectResponse(
            "/login?error=" + _q("That sign-in link expired or was tampered with. Try again."),
            status_code=303)
    if not code:
        return RedirectResponse("/login?error=" + _q(f"{p.label} returned no code."),
                                status_code=303)

    if p.key == "apple":
        # Apple has no userinfo endpoint — the identity arrives inside the
        # id_token from the token exchange, so this is one call, not two.
        profile = _oauth.exchange_apple_code(code)
    else:
        token = _oauth.exchange_code(p, code)
        profile = _oauth.fetch_profile(p, token) if token else None
    if profile is None:
        return RedirectResponse(
            "/login?error=" + _q(f"Could not read your {p.label} account. Try again."),
            status_code=303)

    user = store.find_by_oauth(p.key, profile.subject)
    if user is None:
        user = _link_or_create_oauth_user(p, profile)
        if user is None:
            return RedirectResponse(
                "/login?error=" + _q(
                    f"Your {p.label} account isn't linked to a hub account. Sign in "
                    "with your password first, then link it from Settings."),
                status_code=303)

    if user.totp_enabled:
        # OAuth proves the provider account, not the second factor. Skipping it
        # here would make 2FA bypassable by anyone holding the linked inbox.
        resp = RedirectResponse("/auth/two-factor", status_code=303)
        kw = dict(_cookie_kwargs())
        kw["max_age"] = PENDING_2FA_TTL_S
        resp.set_cookie(PENDING_2FA_COOKIE, _pending_2fa_token(user.username), **kw)
        return resp
    return _grant_session(user)


def _link_or_create_oauth_user(p, profile):
    """Resolve a first-time federated sign-in to a local account.

    Auto-linking by email is only safe when the PROVIDER says the address is
    verified — an unverified one is just a string the user typed, and honouring
    it would let anyone who sets that address inherit the account.

    Creating a brand-new account is allowed only when signup is still open, so
    OAuth cannot become a side door around the single-owner rule.
    """
    if profile.email and profile.email_verified:
        existing = store.find_by_email(profile.email)
        if existing is not None:
            store.link_oauth(p.key, profile.subject, existing.username, profile.email)
            return store.get_user(existing.username)

    if not _signup_open() or not profile.email or not profile.email_verified:
        return None
    username = profile.email
    if store.get_user(username) is None:
        # No password: this account signs in through the provider. A reset link
        # is how they would add one later.
        store.create_user(username, secrets.token_urlsafe(32), role="owner")
        store.set_email(username, profile.email, verified=True)
    store.link_oauth(p.key, profile.subject, username, profile.email)
    return store.get_user(username)


@app.get("/auth/oauth/links")
def oauth_links(request: Request):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    return {"links": store.list_oauth_links(u), "providers": _oauth.available()}


@app.post("/auth/oauth/{provider}/unlink")
def oauth_unlink(request: Request, provider: str):
    u = _user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Sign in first")
    store.unlink_oauth(provider, u)
    return {"ok": True, "links": store.list_oauth_links(u)}


# ------------------------------------------------- persistent user workspace
# Per-user settings blobs (namespace -> JSON), session-authenticated and
# strictly isolated by username. The backend DB is the source of truth; the
# frontends use localStorage only as a fast-boot cache. Nothing here is ever
# reset implicitly — DELETE is wired only to the user's explicit Reset actions.
_SETTINGS_NAMESPACES = ("settings-center", "dashboard", "preferences", "profile")


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
    if _has_role(request, "admin"):
        err = f'<div class="err">{w.esc(error)}</div>' if error else ""
        # only the owner may mint admins (privilege-escalation guard); everyone
        # with the Add-User form can create viewers and operators.
        admin_opt = '<option value="admin">admin</option>' if _has_role(request, "owner") else ""
        form = ('<div class="card"><h2>Add User</h2>'
                '<form method="post" action="/users"><div class="formgrid">'
                '<div><label>Username</label><input name="username" required></div>'
                '<div><label>Password</label><input name="password" type="password" required></div>'
                '<div><label>Role</label><select name="role">'
                '<option value="viewer">viewer</option>'
                '<option value="operator" selected>operator</option>'
                f'{admin_opt}</select></div>'
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
    if not _has_role(request, "admin"):   # rbac: owner + admin may manage users
        return RedirectResponse("/users?error=Admin+only", status_code=303)
    # normalise the requested role to a creatable one (owner is never mintable
    # via the form — there is exactly one owner, seeded at signup).
    role = (role or "operator").strip().lower()
    if role not in ("viewer", "operator", "admin"):
        role = "operator"
    # privilege-escalation guard: only the OWNER may mint admins, so an admin
    # can never create a peer that could in turn lock the owner out.
    if role == "admin" and not _has_role(request, "owner"):
        return RedirectResponse("/users?error=Only+the+owner+can+create+admins",
                                status_code=303)
    if store.get_user(username) is not None:
        return RedirectResponse("/users?error=User+already+exists", status_code=303)
    store.create_user(username, password, role=role)
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
    from services.tenancy import multi_user_enabled
    return {"status": "ok", "app": settings.app_name, **_deploy_info(),
            "persistence": _persistence_info(),
            "tenancy": {"multi_user": multi_user_enabled(), "mode": "multi" if multi_user_enabled() else "single-owner"}}


@app.get("/version")
def version():
    """The deployed build's commit/branch — match commit_short to `git log`."""
    return {"app": settings.app_name, **_deploy_info()}


# ─────────────────────────────────────────────────────────── account page
@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request):
    """Profile, devices and account deletion, in one page.

    Server-rendered like /login and /settings rather than added to the React
    dashboard: this page must work when the dashboard bundle does not, because
    "sign out my other devices" is exactly what someone reaches for when
    something is wrong.

    It renders from the same /account/* JSON the API exposes, so the page and an
    API client cannot disagree about what the account looks like.
    """
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    user = store.get_user(u) or store.get_user(str(u))
    if user is None:
        return RedirectResponse("/login", status_code=303)

    from services.session_auth import split_session
    _who, current_sid = split_session(request.cookies.get(COOKIE, ""),
                                      settings.secret_key)
    sessions = store.list_sessions(user.username)

    def esc(x):
        return w.esc(str(x or ""))

    rows = []
    for s in sessions:
        is_current = bool(current_sid) and s["id"] == current_sid
        agent = esc(s["user_agent"] or "unknown device")
        # Truncated for the table; the full string is in the title attribute so
        # nothing is hidden, just not shouted.
        short = agent if len(agent) <= 48 else agent[:45] + "…"
        badge = ('<span class="pill pill-ok">this device</span>' if is_current
                 else '<span class="pill">%s</span>' % ("remembered" if s["remembered"] else "session"))
        action = ("" if is_current else
                  f'<form method="post" action="/account/sessions/{esc(s["id"])}/revoke-form" '
                  f'style="margin:0"><button class="btn btn-sm">Sign out</button></form>')
        rows.append(
            f'<tr><td title="{agent}">{short}</td><td>{esc(s["ip"])}</td>'
            f'<td>{esc((s["last_seen"] or "")[:16].replace("T", " "))}</td>'
            f'<td>{badge}</td><td style="text-align:right">{action}</td></tr>')
    if not rows:
        rows.append('<tr><td colspan="5" class="muted">No recorded devices yet — '
                    'sessions started before this release are not listed. Sign out '
                    'and back in to record this one.</td></tr>')

    two_fa = "On" if user.totp_enabled else "Off"
    verified = "Verified" if user.email_verified else "Not verified"
    # The form handlers report failure by redirecting back here with ?error=.
    # Without rendering it, a rejected password on the delete form looks exactly
    # like a page that did nothing — the worst possible feedback on the one form
    # where the user needs to know why it refused.
    flash = ""
    if request.query_params.get("error"):
        flash = ('<div class="card danger" style="margin-bottom:16px">%s</div>'
                 % esc(request.query_params["error"]))
    elif request.query_params.get("saved"):
        flash = ('<div class="card" style="margin-bottom:16px">Profile saved.</div>')
    inner = f"""
{flash}
<div class="grid2">
  <section class="card">
    <h3>Profile</h3>
    <form method="post" action="/account/profile-form" class="stack">
      <label>Full name
        <input name="full_name" value="{esc(user.full_name)}" placeholder="Your name" maxlength="120">
      </label>
      <label>Time zone
        <input name="timezone" value="{esc(user.timezone)}" placeholder="Europe/London" maxlength="64">
      </label>
      <label>Avatar URL
        <input name="avatar_url" value="{esc(user.avatar_url)}" placeholder="https://…" maxlength="500">
      </label>
      <button class="btn btn-primary">Save changes</button>
    </form>
    <dl class="kv">
      <dt>Signed in as</dt><dd>{esc(user.username)}</dd>
      <dt>Email</dt><dd>{esc(user.email) or "—"} <span class="muted">({verified})</span></dd>
      <dt>Role</dt><dd>{esc(user.role)}</dd>
      <dt>Two-factor</dt><dd>{two_fa}</dd>
      <dt>Last sign-in</dt>
      <dd>{esc((user.last_login.isoformat()[:16].replace("T", " ")) if user.last_login else "—")}</dd>
    </dl>
  </section>

  <section class="card">
    <h3>Devices</h3>
    <p class="muted">Everywhere this account is signed in. Revoking takes effect
      on that device's next request, not when its cookie expires.</p>
    <table class="tbl">
      <thead><tr><th>Device</th><th>IP</th><th>Last seen</th><th></th><th></th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <form method="post" action="/account/sessions/revoke-others-form" style="margin-top:12px">
      <button class="btn">Sign out all other devices</button>
    </form>
  </section>
</div>

<section class="card danger" style="margin-top:16px">
  <h3>Delete account</h3>
  <p class="muted">Your account is disabled immediately and every session is
    revoked. It can be restored by an administrator for 30 days, after which it
    is permanently removed along with its trades and journal.</p>
  <form method="post" action="/account/delete-form" class="stack"
        onsubmit="return confirm('Delete this account? Sessions end immediately.')">
    <label>Confirm your password
      <input type="password" name="password" required autocomplete="current-password">
    </label>
    <label>Type DELETE to confirm
      <input name="confirm" required placeholder="DELETE" autocomplete="off">
    </label>
    <button class="btn btn-danger">Delete my account</button>
  </form>
</section>
"""
    return _simple_page(request, "Account", "account", inner)


# Form counterparts to the JSON API. A browser <form> cannot send PATCH or a
# JSON body, and requiring JavaScript for "sign out my stolen laptop" would put
# the security control behind the thing most likely to be broken.
@app.post("/account/profile-form")
def account_profile_form(request: Request, full_name: str = Form(""),
                         timezone: str = Form(""), avatar_url: str = Form("")):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    store.update_profile(str(u), full_name=full_name, timezone=timezone,
                         avatar_url=avatar_url)
    return RedirectResponse("/account?saved=1", status_code=303)


@app.post("/account/sessions/{session_id}/revoke-form")
def account_revoke_form(session_id: str, request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    store.revoke_session(str(u), session_id)
    return RedirectResponse("/account", status_code=303)


@app.post("/account/sessions/revoke-others-form")
def account_revoke_others_form(request: Request):
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    from services.session_auth import split_session
    _who, current = split_session(request.cookies.get(COOKIE, ""), settings.secret_key)
    store.revoke_all_sessions(str(u), except_id=current)
    return RedirectResponse("/account", status_code=303)


@app.post("/account/delete-form")
def account_delete_form(request: Request, password: str = Form(...),
                        confirm: str = Form("")):
    """Same two guards as the JSON endpoint — a form must not be the weaker door."""
    u = _require(request)
    if isinstance(u, RedirectResponse):
        return u
    username = str(u)
    if confirm.strip().upper() != "DELETE":
        return RedirectResponse("/account?error=" + _q("Type DELETE to confirm."),
                                status_code=303)
    if store.authenticate(username, password) is None:
        return RedirectResponse("/account?error=" + _q("That password is incorrect."),
                                status_code=303)
    user = store.get_user(username)
    if getattr(user, "role", "") == "owner":
        others = [x for x in store.list_users()
                  if x.role == "owner" and x.active and x.username != username]
        if not others:
            return RedirectResponse(
                "/account?error=" + _q("You are the only owner — promote another "
                                       "owner first, or this deployment would be "
                                       "left with no administrator."),
                status_code=303)
    store.soft_delete_user(username)
    resp = RedirectResponse("/login?error=" + _q("Your account has been deleted."),
                            status_code=303)
    resp.delete_cookie(COOKIE)
    return resp
