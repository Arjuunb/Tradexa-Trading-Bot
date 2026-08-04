# First deploy — the one page

Everything you have to do **yourself** to take TradeLogX from the repo to a
working production deployment on the Hostinger VPS, in the order it has to
happen. Nothing here can be done from the code side: each item is a secret, a
DNS record, a disk, or an account on somebody else's system.

Three sections:

- **[Blocking](#1-blocking)** — get these wrong and the deploy is broken or unsafe.
- **[Same day](#2-same-day)** — needed before anyone but you signs in.
- **[Optional](#3-optional)** — each unlocks a feature; skipping one leaves that
  feature honestly reporting itself as unavailable rather than failing.

The HTTPS mechanics live in [`DEPLOYMENT_VPS.md`](DEPLOYMENT_VPS.md) and are not
repeated here — step 1.4 just says when to run them.

---

## 1. Blocking

### 1.1 Persistent data directory

**Why this is first:** without it, every redeploy wipes trade history, learned
lessons, user accounts, and the journal. The container filesystem is ephemeral;
`HUB_DATA_DIR` is what moves state off it. Everything else on this page is
recoverable by re-running a command — this one is not.

On the VPS, in `/opt/VPS-productn/compose.yaml`, the `app` service needs a named
volume and the variable that points at it:

```yaml
services:
  app:
    environment:
      HUB_DATA_DIR: /var/hubdata
    volumes:
      - hubdata:/var/hubdata

volumes:
  hubdata:
```

> `volumes:` is a **list**, and Compose *replaces* lists rather than merging
> them. If the service already has mounts, add this line to the existing list —
> do not paste a second `volumes:` key.

Verify after the stack is up — the database has to be under the mount, not in
the image:

```bash
docker compose exec app python -c "from config import settings; print(settings.db_path)"
# expect /var/hubdata/hub.db   (NOT /app/logs/hub.db)
docker compose exec app ls -la /var/hubdata
```

Then prove it survives a restart, which is the only test that actually counts:

```bash
docker compose down && docker compose up -d
# sign in — your account should still be there
```

Schema migrations (`database/migrations/*.sql`, including `0005_profiles_sessions`)
run **automatically at boot** and are forward-only and recorded, so this is not a
step you perform. Nothing to do beyond having the directory persist.

### 1.2 The three secrets

Defaults exist so the app runs out of the box for development. In production all
three are a compromise: `HUB_SECRET` signs session cookies, so its default lets
anyone mint a valid session for any user.

```bash
# Run this three times and paste the values into your .env — never reuse one.
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Variable | What it protects | If left at default |
| --- | --- | --- |
| `HUB_SECRET` | Session cookie signature | **Anyone can forge a login.** |
| `HUB_WEBHOOK_SECRET` | The `X-Webhook-Secret` header on `/webhook` | Anyone can inject trading signals. |
| `HUB_API_KEY` | Dashboard/control endpoints | Falls back to the webhook secret, so a TradingView-shared secret also controls the bot. |

Set `HUB_API_KEY` to something *different* from `HUB_WEBHOOK_SECRET`, then set
`HUB_SCOPE_WEBHOOK=1`. That combination is what stops a leaked TradingView
secret from being able to do anything except post alerts.

The app prints a startup warning for each default still in place. Read the boot
log once and confirm it is silent:

```bash
docker compose logs app | grep -iE 'warning|insecure'
```

### 1.3 DNS

Both records must resolve to the VPS **before** you request a certificate — the
ACME challenge is an HTTP fetch of your own domain, and a dry run against a
domain that does not resolve just burns Let's Encrypt rate limit.

| Record | Name | Value |
| --- | --- | --- |
| A | `trade-logx.com` | your VPS IPv4 |
| A | `www` | your VPS IPv4 |

```bash
dig +short trade-logx.com www.trade-logx.com   # both -> your VPS IP
```

### 1.4 Firewall, then HTTPS

Ports 80 and 443 must be open to the world. Port 8000 should **not** be — nginx
is the only thing that should reach the app.

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

Also confirm Hostinger's own panel firewall allows 80/443. A dropped SYN and a
misconfigured app look identical from outside (`nc -zv` times out either way);
this is the cheaper of the two to rule out first.

Then run [`DEPLOYMENT_VPS.md`](DEPLOYMENT_VPS.md) start to finish — bootstrap,
validate the ACME path, dry run, issue, activate TLS, install the renewal timer.
It is written to be followed literally and never takes the HTTP site down.

### 1.5 Lock down CORS

Once the domain is live, name it. Unset means `*`.

```bash
HUB_CORS_ORIGINS=https://trade-logx.com,https://www.trade-logx.com
```

---

## 2. Same day

### 2.1 Claim the owner account

Signup is open **only while the hub has no users**, and it mints the single
owner. So the first thing to do on a fresh deployment, before sharing the URL
with anyone, is visit `https://trade-logx.com/signup` and create your account.
After that the route closes itself and further accounts come from `/users`.

The owner cannot delete themselves while they are the only owner — the deploy
would be left with no administrator and no way back in, since signup only
re-opens when there are no users *at all*.

### 2.2 Walk the account page

`https://trade-logx.com/account` — set your name and timezone, confirm your
device is listed and marked "this device", and check that "sign out all other
devices" leaves you signed in. Two minutes, and it verifies the session table is
actually recording rows on the live deployment rather than silently no-op'ing.

### 2.3 Turn on two-factor

The owner account can start every strategy and move every setting. `/settings`.

---

## 3. Optional

Each block below is self-contained. Skip any of them and the corresponding
feature reports itself unavailable — it does not fail, and it does not fake it.

### 3.1 Email (password reset, verification, alerts)

Without SMTP there is no password reset, which matters more than it sounds: an
owner who forgets their password on a hub with no second owner has no way in.

```bash
ALERT_SMTP_HOST=smtp.example.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USER=you@example.com
ALERT_SMTP_PASS=…                      # app password, not your login password
HUB_MAIL_FROM=TradeLogX <no-reply@trade-logx.com>
HUB_PUBLIC_URL=https://trade-logx.com  # used to build links in emails
```

`HUB_PUBLIC_URL` is required for the links to be clickable — without it a reset
email contains a relative path. Test by triggering one reset to yourself.

### 3.2 Social sign-in

`HUB_PUBLIC_URL` must be set for any of these; it is what the redirect URI is
built from, and the value has to match what you register with the provider
**exactly**, character for character.

| Provider | Variables | Redirect URI to register |
| --- | --- | --- |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `https://trade-logx.com/auth/oauth/google/callback` |
| GitHub | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `https://trade-logx.com/auth/oauth/github/callback` |
| Apple | `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` | `https://trade-logx.com/auth/oauth/apple/callback` |

Do not transcribe those by hand — ask the running app, which builds them from
`HUB_PUBLIC_URL` the same way the real flow does:

```bash
docker compose exec app python -c \
  "from services.oauth import available; import json; print(json.dumps(available(), indent=2))"
```

That also names the exact variable each provider is still missing.

**Apple is different from the other two** and worth reading before you start —
it needs a paid Apple Developer account (~£79/yr) and four values, not two:

1. **Services ID** (Certificates, Identifiers & Profiles → Identifiers → *Services IDs*)
   — this is `APPLE_CLIENT_ID`, e.g. `com.tradelogx.web`. It is **not** your app
   bundle ID. Enable "Sign in with Apple" on it and register the return URL
   above under its Configure button. Apple rejects `http://` and rejects bare
   IPs, so this one genuinely cannot be tested before §1.4 is done.
2. **Team ID** — top right of the developer portal. `APPLE_TEAM_ID`.
3. **Key** (Keys → new key → enable Sign in with Apple) — downloads a `.p8` file
   **once**, and Apple will not give it to you again. The key's ID is
   `APPLE_KEY_ID`; the file's contents are `APPLE_PRIVATE_KEY`.
4. Apple has no static client secret: it is a short-lived ES256 JWT that the app
   mints from the `.p8` on every exchange. You supply the key, not a secret.

Put the `.p8` into the environment with literal `\n` for newlines (a `.env` file
cannot hold a real multi-line value):

```bash
APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIGT…\n-----END PRIVATE KEY-----"
```

Also note Apple sends the user's **name only once**, on the very first
authorisation, in the POST body of the callback. If you delete the test account
and sign in again, the name will not come back — Apple considers you already
told. That is Apple's behaviour, not a bug in the hub.

`/login` shows only the providers that are fully configured, and the boot log
names any single variable that is missing rather than saying "Apple is off".

### 3.3 The separated admin portal

User management can run as its own process, so that a compromise of the trading
app — the thing parsing webhooks from the internet — does not reach the surface
that can grant privilege.

```bash
# On the VPS, alongside the app. Loopback only: no public port.
HUB_ADMIN_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
uvicorn admin_app:app --host 127.0.0.1 --port 8001
```

Reach it over an SSH tunnel rather than publishing it:

```bash
ssh -L 8001:127.0.0.1:8001 you@your-vps    # then open http://localhost:8001
```

Only `admin` and `owner` accounts can sign in at all — everyone else is refused
at the door, not shown an empty page. If the account has two-factor on, the
portal demands it; it is not a way around 2FA. Every action, **including every
refusal**, is appended to `admin_audit.jsonl` under `HUB_DATA_DIR`.

`HUB_ADMIN_SECRET` is a hardening step, not the mechanism: portal cookies are
signed with a purpose-scoped key, so a stolen trading-app session cookie cannot
open the portal even if you never set it. Setting it separates the raw key
material too.

The main app's `/users` page is unchanged and still works — this adds a safer
door rather than removing the existing one.

### 3.4 TradingView alerts

Point the webhook at `https://trade-logx.com/webhook` with the header
`X-Webhook-Secret: <HUB_WEBHOOK_SECRET>`. Now that HTTPS is on, the secret is no
longer crossing the internet in plaintext — do not go back to the `http://` or
`:8000` URL for this.

---

## Final verification

```bash
curl -sSI https://trade-logx.com | head -1              # HTTP/2 200
curl -sS  https://trade-logx.com/health                 # ok
curl -sSI http://trade-logx.com | grep -i location      # -> https://…
docker compose logs app | grep -iE 'warning|insecure'   # silent
docker compose exec app python -c "from config import settings; print(settings.db_path)"
```

Then the one that is not a command: **restart the stack and sign in again.** If
your account, your trades, and your settings are all still there, the deployment
is real. If they are not, stop and go back to §1.1 — nothing else on this page
matters until state survives a restart.
