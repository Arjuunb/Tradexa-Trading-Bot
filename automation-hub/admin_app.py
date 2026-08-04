"""The separated administration portal — a second ASGI app, its own process.

    uvicorn admin_app:app --host 127.0.0.1 --port 8001

Why a second process rather than a `/admin` prefix in the trading app: user
management is the only surface that can grant privilege, and it should not share
an address space, a request pipeline, or a public port with the code that parses
webhooks from the internet. Bind it to loopback and reach it over an SSH tunnel,
or put it behind its own nginx server block with an IP allowlist; either way, a
compromise of the trading app does not reach it.

The separation is enforced in code, not by deployment discipline:

- Portal cookies are signed with a purpose-scoped key, so a stolen trading-app
  session cookie cannot be presented here even when both apps share HUB_SECRET
  (``services.admin_portal``, tested directly).
- Every authorisation question is answered by ``services.admin_portal``, a pure
  module with no HTTP in it, so the rules can be tested against every
  actor/target combination and cannot drift between a page and the form that
  posts to it.
- Two-factor is **not optional here.** If an admin has TOTP enabled, the portal
  demands it — a second door that skipped it would make 2FA advisory.
- Every mutation is appended to an audit log before the response is written.

It shares the SQLite store with the trading app, which is the point: it is the
same accounts, administered from somewhere safer.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import DATA_DIR, settings
from database.store import SqliteStore
from services import admin_portal as policy
from services import auth_flows as _af

app = FastAPI(title="TradeLogX Administration", docs_url=None, redoc_url=None,
              openapi_url=None)

store = SqliteStore(settings.db_path)

COOKIE = "hub_admin_session"
#: Long enough to hold a pending 2FA prompt, short enough that an abandoned one
#: is not a standing invitation.
PENDING_COOKIE = "hub_admin_pending"
PENDING_TTL_S = 5 * 60

AUDIT_PATH = Path(os.environ.get("HUB_ADMIN_AUDIT") or (DATA_DIR / "admin_audit.jsonl"))


# ─────────────────────────────────────────────────────────────────── audit

def _audit(actor: str, action: str, target: str = "", detail: str = "",
           allowed: bool = True) -> None:
    """Append one line per attempt — including refusals.

    Refusals are the more interesting half: a run of them is what an attempt to
    escalate looks like, and a log that records only successes cannot show it.
    Failures to write are swallowed on purpose; an unwritable log must not take
    the portal down, and the boot check below is where that gets noticed.
    """
    line = {"at": datetime.now(timezone.utc).isoformat(), "actor": actor,
            "action": action, "target": target, "detail": detail,
            "allowed": allowed}
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError as exc:                                  # pragma: no cover
        print(f"[admin] AUDIT WRITE FAILED ({exc}) — {line}", flush=True)


@app.on_event("startup")
def _boot_checks() -> None:
    if not os.environ.get("HUB_ADMIN_SECRET"):
        print("[admin] HUB_ADMIN_SECRET is unset — portal cookies are signed "
              "with HUB_SECRET. They still cannot be interchanged with trading "
              "sessions (the key is purpose-scoped), but setting a dedicated "
              "secret separates the raw key material too.", flush=True)
    print(f"[admin] audit log: {AUDIT_PATH}", flush=True)


# ─────────────────────────────────────────────────────────────────── chrome
_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0B0B0D;color:#E8E8EA;font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 20px 64px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;border-bottom:1px solid #26262B;padding-bottom:16px;margin-bottom:26px}
h1{font-size:19px;margin:0;letter-spacing:-.01em}
.tag{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#0B0B0D;background:#C9A24B;padding:3px 8px;border-radius:5px;font-weight:700}
.who{margin-left:auto;font-size:13px;color:#8B8B93}
.who a{color:#C9A24B}
.card{background:#131318;border:1px solid #26262B;border-radius:12px;padding:20px;margin-bottom:18px}
h2{font-size:15px;margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:600;color:#8B8B93;font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;padding:0 10px 9px 0}
td{padding:10px 10px 10px 0;border-top:1px solid #202026;vertical-align:middle}
.role{font-size:11.5px;padding:2px 8px;border-radius:20px;border:1px solid #33333A;color:#B9B9C0}
.role.owner{border-color:#C9A24B;color:#E4C579}
.role.admin{border-color:#4C7FE0;color:#8FB1F0}
.off{color:#E5605B}
input,select{background:#0B0B0D;border:1px solid #33333A;color:#E8E8EA;border-radius:8px;padding:8px 10px;font:inherit;font-size:13.5px}
button{background:#C9A24B;color:#0B0B0D;border:0;border-radius:8px;padding:8px 13px;font:inherit;font-weight:650;font-size:13px;cursor:pointer}
button.q{background:#232329;color:#D8D8DE}
button.d{background:#3A1F1F;color:#F0918D}
form.inline{display:inline;margin:0}
.msg{padding:11px 13px;border-radius:9px;margin-bottom:18px;font-size:13.5px}
.msg.err{background:#2A1618;border:1px solid #5A2A2C;color:#F0918D}
.msg.ok{background:#132A1E;border:1px solid #2A5A3E;color:#8FE0B0}
.hint{color:#8B8B93;font-size:12.5px;margin:10px 0 0}
.login{max-width:380px;margin:14vh auto;padding:0 20px}
label{display:block;font-size:12.5px;color:#8B8B93;margin:14px 0 5px}
.login input{width:100%}
.login button{width:100%;margin-top:18px;padding:11px}
"""


def esc(x) -> str:
    from html import escape
    return escape(str(x if x is not None else ""))


def _page(title: str, body: str, who: str = "") -> HTMLResponse:
    ident = (f'<div class="who">{esc(who)} · '
             f'<a href="/logout">Sign out</a></div>') if who else ""
    return HTMLResponse(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex,nofollow">'
        f'<title>{esc(title)} · Administration</title><style>{_CSS}</style></head>'
        f'<body><div class="wrap"><header><h1>TradeLogX Administration</h1>'
        f'<span class="tag">restricted</span>{ident}</header>{body}</div></body></html>')


def _flash(request: Request) -> str:
    error, ok = request.query_params.get("error"), request.query_params.get("ok")
    if error:
        return f'<div class="msg err">{esc(error)}</div>'
    if ok:
        return f'<div class="msg ok">{esc(ok)}</div>'
    return ""


def _q(text: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(text or "")


def _cookie_kwargs(max_age: int) -> dict:
    return {"httponly": True, "samesite": "lax", "max_age": max_age,
            "secure": os.environ.get("HUB_COOKIE_SECURE", "1") not in ("0", "false", "")}


# ───────────────────────────────────────────────────────────────── identity

def _actor(request: Request):
    """The signed-in admin, re-checked from the store on every request.

    Re-reading the row rather than trusting the cookie's claim is what makes a
    demotion or a disable take effect on the next click instead of when the
    cookie expires — which for an account you have just decided to distrust is
    the only timing that counts.
    """
    username, session_id = policy.read_session(request.cookies.get(COOKIE, ""),
                                               policy.admin_secret())
    if not username:
        return None
    if session_id and not store.session_is_valid(session_id):
        return None
    user = store.get_user(username)
    return user if policy.may_sign_in(user)[0] else None


def _require(request: Request):
    actor = _actor(request)
    if actor is None:
        return None, RedirectResponse("/login", status_code=303)
    return actor, None


# ──────────────────────────────────────────────────────────────────── login

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _actor(request) is not None:
        return RedirectResponse("/", status_code=303)
    return _page("Sign in", f'''<div class="login">{_flash(request)}
<form method="post" action="/login">
  <label>Username</label><input name="username" autocomplete="username" autofocus>
  <label>Password</label><input name="password" type="password" autocomplete="current-password">
  <button>Sign in</button>
</form>
<p class="hint">Administrators only. Everyone else signs in at the main
application.</p></div>''')


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = store.authenticate(username, password)
    if user is None:
        # Deliberately not distinguishing "no such account" from "wrong
        # password" here, unlike the main app: this surface is not public and
        # has nothing to gain from the friendlier message.
        _audit(username, "login", allowed=False, detail="bad credentials")
        return RedirectResponse("/login?error=" + _q("Incorrect username or password"),
                                status_code=303)
    allowed, reason = policy.may_sign_in(user)
    if not allowed:
        _audit(user.username, "login", allowed=False, detail=reason)
        return RedirectResponse("/login?error=" + _q(reason), status_code=303)

    if user.totp_enabled:
        # A portal that skipped the second factor would be the way to avoid it.
        from services.session_auth import sign_scoped
        resp = RedirectResponse("/two-factor", status_code=303)
        resp.set_cookie(PENDING_COOKIE,
                        sign_scoped(user.username, policy.admin_secret(),
                                    purpose="admin_2fa", ttl_s=PENDING_TTL_S),
                        **_cookie_kwargs(PENDING_TTL_S))
        return resp
    return _grant(user, request)


def _grant(user, request: Request) -> RedirectResponse:
    sid = f"admin-{os.urandom(12).hex()}"
    store.create_session(user.username, sid, ttl_days=1,
                         user_agent=(request.headers.get("user-agent") or "")[:180],
                         ip=(request.client.host if request.client else None))
    store.touch_login(user.username)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE,
                    policy.mint_session(user.username, sid, policy.admin_secret()),
                    **_cookie_kwargs(policy.DEFAULT_TTL_S))
    resp.delete_cookie(PENDING_COOKIE)
    _audit(user.username, "login", detail="portal session opened")
    return resp


@app.get("/two-factor", response_class=HTMLResponse)
def two_factor_page(request: Request):
    return _page("Two-factor", f'''<div class="login">{_flash(request)}
<form method="post" action="/two-factor">
  <label>Authenticator code</label>
  <input name="code" autocomplete="one-time-code" inputmode="text" autofocus>
  <button>Verify</button>
</form>
<p class="hint">A recovery code works here too.</p></div>''')


@app.post("/two-factor")
def two_factor(request: Request, code: str = Form(...)):
    from services.session_auth import verify_scoped
    pending = verify_scoped(request.cookies.get(PENDING_COOKIE, ""),
                            policy.admin_secret(), purpose="admin_2fa")
    if not pending:
        return RedirectResponse("/login?error=" + _q("That sign-in expired. Try again."),
                                status_code=303)
    result = _af.verify_second_factor(store, pending, code)
    if not result["ok"]:
        _audit(pending, "two_factor", allowed=False, detail=result["error"])
        return RedirectResponse("/two-factor?error=" + _q(result["error"]),
                                status_code=303)
    user = store.get_user(pending)
    allowed, reason = policy.may_sign_in(user)
    if not allowed:
        # The role can have changed between the password and the code.
        return RedirectResponse("/login?error=" + _q(reason), status_code=303)
    return _grant(user, request)


@app.get("/logout")
def logout(request: Request):
    _who, session_id = policy.read_session(request.cookies.get(COOKIE, ""),
                                           policy.admin_secret())
    actor = _actor(request)
    if actor and session_id:
        store.revoke_session(actor.username, session_id, by="user")
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ───────────────────────────────────────────────────────────────── the list

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    actor, redirect = _require(request)
    if redirect:
        return redirect

    users = store.list_users()
    rows = []
    for u in sorted(users, key=lambda x: (not x.active, x.role != "owner", x.username)):
        role_cls = u.role if u.role in ("owner", "admin") else ""
        state = ("" if u.active
                 else '<span class="off">disabled</span>')
        actions = []
        if policy.may_set_role(actor, u, "operator", users)[0]:
            options = "".join(
                f'<option value="{r}"{" selected" if r == u.role else ""}>{r}</option>'
                for r in policy.GRANTABLE_ROLES)
            actions.append(
                f'<form class="inline" method="post" action="/users/{esc(u.username)}/role">'
                f'<select name="role">{options}</select> '
                f'<button class="q">Set</button></form>')
        if u.active and policy.may_disable(actor, u, users)[0]:
            actions.append(
                f'<form class="inline" method="post" action="/users/{esc(u.username)}/disable" '
                f'onsubmit="return confirm(\'Disable {esc(u.username)}? Every session ends immediately.\')">'
                f'<button class="d">Disable</button></form>')
        if not u.active and policy.may_restore(actor, u)[0]:
            actions.append(
                f'<form class="inline" method="post" action="/users/{esc(u.username)}/restore">'
                f'<button class="q">Restore</button></form>')
        if policy.may_revoke_sessions(actor, u)[0]:
            actions.append(
                f'<form class="inline" method="post" action="/users/{esc(u.username)}/revoke">'
                f'<button class="q">Sign out</button></form>')
        sessions = len(store.list_sessions(u.username)) if u.active else 0
        last = u.last_login.isoformat()[:16].replace("T", " ") if u.last_login else "—"
        rows.append(
            f'<tr><td><b>{esc(u.username)}</b> {state}</td>'
            f'<td><span class="role {role_cls}">{esc(u.role)}</span></td>'
            f'<td>{sessions}</td><td>{esc(last)}</td>'
            f'<td style="text-align:right">{" ".join(actions) or "—"}</td></tr>')

    create = ""
    if policy.may_create(actor, "viewer")[0]:
        grantable = [r for r in policy.GRANTABLE_ROLES
                     if policy.may_create(actor, r)[0]]
        options = "".join(f'<option value="{r}">{r}</option>' for r in grantable)
        create = f'''<section class="card"><h2>Create an account</h2>
<form method="post" action="/users">
  <input name="username" placeholder="name@example.com" required>
  <input name="password" type="password" placeholder="password" required>
  <select name="role">{options}</select>
  <button>Create</button>
</form>
<p class="hint">The new account signs in at the main application. It appears
here only so its role can be managed.</p></section>'''

    return _page("Accounts", f'''{_flash(request)}
<section class="card"><h2>Accounts</h2>
<table><thead><tr><th>Account</th><th>Role</th><th>Sessions</th>
<th>Last sign-in</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p class="hint">Actions you are not permitted are not rendered — and are refused
again on submit, so a hand-crafted POST gets the same answer as the page.</p>
</section>{create}
<section class="card"><h2>Audit</h2>
<p class="hint">Every attempt, including refusals, is appended to
<code>{esc(AUDIT_PATH)}</code> on the server. Setting another account's password
is deliberately not offered here: an admin who could do it could act as that
person, and every record of what they did would become deniable.</p></section>''',
                 who=f"{actor.username} ({actor.role})")


# ────────────────────────────────────────────────────────────────── actions

def _back(message: str, ok: bool = True) -> RedirectResponse:
    key = "ok" if ok else "error"
    return RedirectResponse(f"/?{key}=" + _q(message), status_code=303)


@app.post("/users")
def create_user(request: Request, username: str = Form(...),
                password: str = Form(...), role: str = Form("viewer")):
    actor, redirect = _require(request)
    if redirect:
        return redirect
    allowed, reason = policy.may_create(actor, role)
    if not allowed:
        _audit(actor.username, "create", username, reason, allowed=False)
        return _back(reason, ok=False)
    if store.get_user(username) is not None:
        return _back("An account with that username already exists", ok=False)
    store.create_user(username, password, role=role.strip().lower())
    _audit(actor.username, "create", username, f"role={role}")
    return _back(f"Created {username}")


@app.post("/users/{username}/role")
def set_role(username: str, request: Request, role: str = Form(...)):
    actor, redirect = _require(request)
    if redirect:
        return redirect
    target = store.get_user(username)
    users = store.list_users()
    allowed, reason = policy.may_set_role(actor, target, role, users)
    if not allowed:
        _audit(actor.username, "set_role", username, reason, allowed=False)
        return _back(reason, ok=False)
    before = target.role
    if not store.set_role(username, role):
        return _back("Nothing changed", ok=False)
    # A role change is a change to what their existing sessions may do. Ending
    # them makes the new role take effect at the next sign-in rather than
    # leaving a live session holding privileges it no longer has.
    store.revoke_all_sessions(target.username, by="role_change")
    _audit(actor.username, "set_role", username, f"{before} -> {role}")
    return _back(f"{username} is now {role}; existing sessions ended")


@app.post("/users/{username}/disable")
def disable_user(username: str, request: Request):
    actor, redirect = _require(request)
    if redirect:
        return redirect
    target = store.get_user(username)
    allowed, reason = policy.may_disable(actor, target, store.list_users())
    if not allowed:
        _audit(actor.username, "disable", username, reason, allowed=False)
        return _back(reason, ok=False)
    store.soft_delete_user(username)          # also revokes every session
    _audit(actor.username, "disable", username, "soft delete")
    return _back(f"{username} disabled. Recoverable here for 30 days.")


@app.post("/users/{username}/restore")
def restore_user(username: str, request: Request):
    actor, redirect = _require(request)
    if redirect:
        return redirect
    target = store.get_user(username)
    allowed, reason = policy.may_restore(actor, target)
    if not allowed:
        _audit(actor.username, "restore", username, reason, allowed=False)
        return _back(reason, ok=False)
    store.restore_user(username)
    _audit(actor.username, "restore", username)
    return _back(f"{username} restored. They must sign in again.")


@app.post("/users/{username}/revoke")
def revoke_sessions(username: str, request: Request):
    actor, redirect = _require(request)
    if redirect:
        return redirect
    target = store.get_user(username)
    allowed, reason = policy.may_revoke_sessions(actor, target)
    if not allowed:
        _audit(actor.username, "revoke", username, reason, allowed=False)
        return _back(reason, ok=False)
    count = store.revoke_all_sessions(target.username, by="admin")
    _audit(actor.username, "revoke", username, f"{count} sessions")
    return _back(f"Signed {username} out of {count} session(s)")


@app.get("/health")
def health():
    return {"ok": True, "app": "admin-portal"}
