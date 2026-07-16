# Audit Phase 0 — trust & safety hot-fixes

Closes the audit's Critical + the highest-impact High/Medium items. All verified
in-source and covered by tests.

## CR-1 — session forgery / privilege escalation (Critical)
Sessions were HMAC-signed with `webhook_secret`, which is embedded in every
authenticated page — so any logged-in user could read it and forge an `owner`
cookie. **Fix:** sessions are now signed with the server-only `secret_key`
(`HUB_SECRET`, never embedded). A leaked webhook secret can no longer mint a
session. (`app.py` `_sign_session`/`_verify_session`.)

## M-7 — insecure defaults reach production
On a cloud host (`RENDER`/`DYNO`), the app now **refuses to boot** if
`HUB_SECRET` is the dev default (session forgery would be trivial), and prints a
loud warning if `HUB_PASSWORD` is still `admin`. Never fires on a correct deploy
(`render.yaml` generates `HUB_SECRET`) or under tests/local dev.

## H-2 — anonymous read of live config
The landing bundle exempted the `/settings` prefix so its SPA routes load, but
that also exposed the bare `/settings` **API** (live strategy/risk/symbols).
**Fix:** exempt only `/settings/` sub-routes; the bare `/settings` API is
session-gated again.

## M-3 — unlocked shared SQLite store
`SqliteStore` (users, settings, bots) is shared between request threads and the
bot lifecycle but had no lock (every other store does). **Fix:** added an
`RLock` around its writes + `busy_timeout` so concurrent access waits instead of
raising “database is locked”.

## H-3 — misleading exchange-key security messaging
The Exchange Connections page toasted “keys saved and encrypted” and showed
“Keys are encrypted before storage / we verify keys are trade-only”, but
`save()` stored nothing and nothing was encrypted or verified. **Fix:** a clear
“Preview — not wired to the engine; paper mode; keys are not stored or
transmitted” notice, honest toast, and the encryption/verification claims
removed (the good “use trade-only keys, no withdrawals” advice stays).

## H-6 — destructive controls with no confirmation
Stop Engine / Pause All / Stop All on Paper Trading now confirm before firing,
matching the Safety Center kill-switch and Settings resets. (The header
strategy/timeframe switch is intentionally left immediate — it’s a
fast-switch menu control that already announces “engine restarted”.)

## M-2 — polling intervals leaked on unmount
`LoadDataButton` and `ControlBar` tracked their status-poll id in a `useRef` and
now `clearInterval` on unmount, so navigating away mid-load no longer leaves an
interval firing `setState` on an unmounted component.

## M-1 — outages shown as a real empty account
Portfolio and Simulation now render a shared **OfflineBanner** when the backend
is unreachable, so `$0` equity reads as “connection issue,” not “wiped account.”

## M-5 — webhook secret decoupled from control (done)
The webhook secret is shared with TradingView (it rides in the alert webhook),
so it is the credential most likely to leak. It used to authorize everything.
Now the dashboard/control credential is a separate **admin key** (`HUB_API_KEY`),
and with `HUB_SCOPE_WEBHOOK=1` the webhook secret is **rejected on every
non-webhook endpoint** — it can post alerts but cannot stop the engine, reset the
account, or change settings. Default behaviour is unchanged: the admin key falls
back to the webhook secret until an operator opts in.
- `_check_webhook_secret` guards `/webhook/tradingview`; `_check_secret` (all
  control actions) + the auth wall accept the admin key, and the webhook secret
  only when unscoped. The same-origin dashboard is served the admin key in its
  runtime config; cross-origin (Vercel) sets `VITE_WEBHOOK_SECRET` to the admin
  key. Covered by `tests/test_webhook_scope.py`.
