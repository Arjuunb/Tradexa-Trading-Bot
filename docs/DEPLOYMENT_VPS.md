# Production HTTPS on the VPS — trade-logx.com

Adds Let's Encrypt TLS to the existing Docker Compose deployment (FastAPI `app`
behind `nginx`) **without taking the working HTTP site down**. The mechanism is
a deliberate two-phase switch:

1. **Bootstrap** — nginx serves HTTP *and* the ACME challenge, so the site keeps
   working while the first certificate is requested.
2. **TLS** — once the certificate exists on disk, swap nginx to a config that
   redirects HTTP → HTTPS (but keeps the ACME path on HTTP for renewals) and
   serves HTTPS.

nginx will not start with an `ssl_certificate` line pointing at a file that does
not exist yet, so the certificate **must** be issued before the TLS config is
activated. That ordering is the whole reason for two phases — follow the steps
in order and the site is never down.

## Files this adds (in the repo, under `deploy/vps/`)

| File | Purpose |
| --- | --- |
| `compose.yaml` | Reference stack: `app` (internal 8000) + `nginx` (80 & 443) + `certbot`, with named volumes `letsencrypt`, `certbot_webroot`, `hubdata` |
| `nginx/conf.d/default.conf` | **Phase A** — HTTP + ACME challenge + reverse proxy (active during issuance) |
| `nginx/conf.d/default.conf.tls` | **Phase B** — HTTP→HTTPS redirect + HTTPS. Filename ends `.tls` so nginx does not load it until you rename it into place |
| `systemd/certbot-renew.{service,timer}` | Twice-daily renewal + nginx reload on success |
| `.gitignore` | Keeps certs / keys / `.env` out of git |

> **Certificates and private keys are never committed.** They live in the
> `letsencrypt` Docker volume on the VPS, and `deploy/vps/.gitignore` blocks them
> even if you switch to a bind mount.

---

## Reconcile with your live compose first (once)

Your real file is `/opt/VPS-productn/compose.yaml`; this repo cannot see it, so
`deploy/vps/compose.yaml` is a **reference to line up against, not a blind
replacement**. Three things must match your existing deployment or you will
break the site or orphan data — in Compose, a service's `ports:` and `volumes:`
are *lists*, and an override file *replaces* a list rather than merging it, so
these have to be edited in place:

1. **App service name + port.** nginx proxies to `app:8000`. If your app service
   is named differently, change `proxy_pass http://app:8000;` in **both** nginx
   configs (and `depends_on`/`condition` in compose).
2. **Persistent trading data.** Keep **your** existing data volume name. The
   reference uses `hubdata:/var/hubdata`; if yours differs, use yours — renaming
   it orphans the ledger's history.
3. **Your other nginx mounts** (static build, existing config). Keep them; just
   **add** the three TLS-related mounts and the `443:443` port shown below.

The additive parts — the `443:443` port, the `letsencrypt` + `certbot_webroot`
volumes, and the entire `certbot` service — copy across verbatim.

Validate the merge before applying anything:

```bash
cd /opt/VPS-productn
docker compose config -q && echo "compose OK"
```

---

## First-time issuance — run these on the VPS, in order

```bash
# 0. Pull the changes and move into the deployment directory.
cd /opt/VPS-productn
git pull        # (or copy deploy/vps/* into place per your workflow)

# Make sure the bootstrap (HTTP-only) nginx config is the active one. It is the
# default in the repo; this is just insurance if you ran TLS before.
ls nginx/conf.d/            # expect: default.conf  default.conf.tls
# If default.conf is currently the TLS version, restore the bootstrap first:
#   git checkout -- nginx/conf.d/default.conf

# 1. Bring the stack up with 80 AND 443 published. HTTP works immediately;
#    443 has no cert yet but the port is open for the moment TLS is activated.
docker compose up -d --build
docker compose ps           # app + nginx should be running/healthy

# 2. VALIDATE the ACME path is served over HTTP before asking Let's Encrypt for
#    anything. Put a probe file in the shared webroot and fetch it through nginx.
docker compose run --rm --entrypoint sh certbot -c \
  'mkdir -p /var/www/certbot/.well-known/acme-challenge && echo ok > /var/www/certbot/.well-known/acme-challenge/ping'
curl -s http://trade-logx.com/.well-known/acme-challenge/ping        # -> ok
curl -s http://www.trade-logx.com/.well-known/acme-challenge/ping    # -> ok
#    Both MUST print `ok`. If not, fix DNS / port 80 before continuing — a dry
#    run against a broken path just burns Let's Encrypt rate limit.

# 3. DRY RUN the issuance (no rate-limit cost). Proves the whole path end to end.
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d trade-logx.com -d www.trade-logx.com \
  --email you@example.com --agree-tos --no-eff-email --dry-run
#    Expect: "The dry run was successful."

# 4. ISSUE the real certificate (covers both the root and www on one cert).
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d trade-logx.com -d www.trade-logx.com \
  --email you@example.com --agree-tos --no-eff-email
#    Expect: "Successfully received certificate." saved under
#    /etc/letsencrypt/live/trade-logx.com/ (inside the letsencrypt volume).

# 5. ACTIVATE TLS: make the TLS config the active one, verify syntax, reload.
cp nginx/conf.d/default.conf.tls nginx/conf.d/default.conf
docker compose exec nginx nginx -t          # MUST say "syntax is ok / test is successful"
docker compose exec nginx nginx -s reload   # zero-downtime; no restart needed
```

If `nginx -t` fails at step 5, **do not reload** — restore the bootstrap config
(`git checkout -- nginx/conf.d/default.conf` or re-copy it) and reload; the HTTP
site stays up while you investigate.

---

## Validate everything (requirement 14)

```bash
# HTTPS on the root domain — expect HTTP/2 200 and a valid Let's Encrypt cert.
curl -sSI https://trade-logx.com | head -1
curl -sS  https://trade-logx.com/health

# HTTPS on www.
curl -sSI https://www.trade-logx.com | head -1

# HTTP → HTTPS redirect (301 to the https URL)...
curl -sSI http://trade-logx.com | grep -iE 'HTTP/|location'

# ...but the ACME path stays on HTTP (200, NOT a redirect) so renewals work.
curl -sSI http://trade-logx.com/.well-known/acme-challenge/ping | head -1

# Certificate expiry / chain.
echo | openssl s_client -servername trade-logx.com -connect trade-logx.com:443 2>/dev/null \
  | openssl x509 -noout -dates -subject -issuer

# Container health.
docker compose ps
docker inspect --format '{{.Name}} {{.State.Health.Status}}' $(docker compose ps -q)

# Tidy up the probe file from step 2.
docker compose run --rm --entrypoint sh certbot -c \
  'rm -f /var/www/certbot/.well-known/acme-challenge/ping'
```

---

## Automatic renewal (requirements 10 + 11)

`certbot renew` is a no-op until a cert is within 30 days of expiry, so it is
safe to run on a schedule. The systemd timer runs it twice a day and reloads
nginx **only on a successful renewal**.

```bash
# Install the unit + timer (edit WorkingDirectory in the .service if your
# deployment dir is not /opt/VPS-productn).
sudo cp deploy/vps/systemd/certbot-renew.service /etc/systemd/system/
sudo cp deploy/vps/systemd/certbot-renew.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now certbot-renew.timer

# Confirm it is scheduled, and prove renewal works without waiting for expiry.
systemctl list-timers certbot-renew.timer
docker compose run --rm certbot renew --webroot -w /var/www/certbot --dry-run
```

The renewer container and nginx share the `letsencrypt` and `certbot_webroot`
volumes, so a renewed certificate is immediately the one nginx serves after the
reload — no copying between containers.

---

## What is preserved (requirement 9)

- **Reverse proxy** to `app:8000` — unchanged in both phases.
- **Security headers** — carried into the HTTPS server block; HSTS added there
  (HTTPS only, never over plain HTTP). Match the set to your existing config.
- **Restart policies** (`unless-stopped`), **health checks**, **bounded logs**
  (`json-file`, 10 MB × 5), and the **persistent data volume** — all retained.
- **nginx read-only root + tmpfs** — kept; config and certs are mounted
  read-only, and the writable runtime paths (`/var/cache/nginx`, `/var/run`,
  `/tmp`) are tmpfs.
