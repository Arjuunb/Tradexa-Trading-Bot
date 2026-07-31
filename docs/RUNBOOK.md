# Runbook

What to do when an alert fires. Every alert in
`deploy/observability/prometheus/rules/hub-alerts.yml` carries a `runbook`
annotation pointing at a section here.

Written for someone who did not build this system and is reading it at 3am.
Commands first, explanation second.

---

## Orientation

```bash
# What is running, and is it healthy?
kubectl -n tradexa get pods -o wide
kubectl -n tradexa get statefulset,deploy

# The single most important question in this system.
kubectl -n tradexa get pods -l app.kubernetes.io/component=engine

# Logs are JSON. jq is your friend.
kubectl -n tradexa logs -l app.kubernetes.io/component=engine --tail=200 | jq -r \
  'select(.level != "INFO") | "\(.timestamp) \(.level) \(.message)"'

# Follow one request across the system.
kubectl -n tradexa logs -l app.kubernetes.io/name=tradexa-hub --tail=5000 \
  | jq -c 'select(.request_id == "THE_ID")'
```

Health endpoints, and what each actually means:

| Endpoint | Question | A failure means |
|---|---|---|
| `/health/live` | Is the process alive? | Restart the pod |
| `/health/ready` | Can it serve traffic? | Take it out of the load balancer — do **not** restart |
| `/health/startup` | Has boot finished? | Still booting; leave it alone |
| `/health` | Full status payload | Diagnostic detail — not a probe |

---

## split-brain-engine

**Alerts:** `HubMultipleEngineLeaders`, `HubMultipleEnginesRunning`
**Severity:** critical. Act immediately.

More than one trading engine is running against the same account. Every signal
is being evaluated twice, so orders are duplicated and real exposure is roughly
double what the risk engine believes it is.

**Stop the bleeding first, diagnose second.**

```bash
# 1. How many, and where?
kubectl -n tradexa get pods -l app.kubernetes.io/component=engine
kubectl -n tradexa get statefulset tradexa-hub-engine -o jsonpath='{.spec.replicas}{"\n"}'

# 2. If replicas > 1, that is the cause. Fix it now.
kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=1

# 3. Check nothing else is running workers: every web pod must say "web".
kubectl -n tradexa get pods -l app.kubernetes.io/component=web \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].env[?(@.name=="HUB_ROLE")].value}{"\n"}{end}'

# 4. Confirm one leader.
curl -s $HUB/metrics | grep -E '^hub_engine_(running|leader)'
```

Then reconcile the account: open positions may be doubled. Check the trade
journal for duplicate entries in the overlap window and close the extras
manually before restarting.

**Root causes, in order of likelihood:** someone scaled the StatefulSet; a web
Deployment was deployed with `HUB_ROLE=all` or unset; two clusters point at the
same account; the lease is disabled (`HUB_SINGLETON_LEASE=0`) *and* replicas
went above one.

`deploy/scripts/validate_manifests.py` fails the build on the first two. If this
fired anyway, something bypassed CI — find out what.

---

## engine-not-running

**Alert:** `HubNoEngineRunning` · critical

No engine is evaluating signals. Open positions are unmanaged: stops and targets
are not being acted on.

```bash
kubectl -n tradexa get pods -l app.kubernetes.io/component=engine
kubectl -n tradexa describe pod -l app.kubernetes.io/component=engine | tail -30
kubectl -n tradexa logs -l app.kubernetes.io/component=engine --tail=100 | jq -r '.message'
```

Work through, in order:

1. **Pod not scheduled?** `describe` shows why — usually the PVC cannot mount
   (ReadWriteMany unavailable) or there are insufficient resources.
2. **CrashLoopBackOff?** Read the logs. A boot-time refusal is deliberate and
   the message says exactly what is wrong — most often `HUB_SECRET` unset.
3. **Running but engine off?** Look for `engine not started`. The `extra` fields
   distinguish the three causes: wrong role, `HUB_AUTO_ENGINE=0`, or under test.
4. **Waiting for the lease?** `curl $POD:8000/health/ready` reports
   `standby — another instance holds the engine lease`. If no other engine
   exists, a dead pod's lease has not expired yet: it clears within
   `HUB_LEASE_TTL_S` (60s default).

---

## engine-stalled

**Alert:** `HubEngineStalled` · critical

The engine thread is alive but has not completed a cycle in 15 minutes. Almost
always a wedged outbound call — an exchange endpoint that accepted the
connection and never answered.

```bash
# When did it last make progress?
curl -s $HUB/metrics | grep hub_engine_last_cycle_timestamp_seconds

# Feed errors and stalls, in order.
kubectl -n tradexa logs -l app.kubernetes.io/component=engine --tail=500 \
  | jq -r 'select(.message | test("fetch|feed|live")) | "\(.timestamp) \(.message)"'

# Is the venue reachable at all?
kubectl -n tradexa exec -it statefulset/tradexa-hub-engine -- \
  python -c "import ccxt; print(ccxt.kraken().fetch_ticker('BTC/USDT')['last'])"
```

If the venue is blocking the cluster's egress IPs (Binance answers HTTP 451 to
most datacenter ranges), switch venue:

```bash
kubectl -n tradexa set env statefulset/tradexa-hub-engine HUB_EXCHANGE=kraken
```

Restarting the pod clears a wedged socket and is safe — the StatefulSet
guarantees the replacement starts only after this one is gone.

---

## service-down

**Alerts:** `HubTargetDown`, `HubNoWebCapacity` · critical

```bash
kubectl -n tradexa get pods -l app.kubernetes.io/component=web
kubectl -n tradexa describe pod -l app.kubernetes.io/component=web | tail -40
kubectl -n tradexa get events --sort-by=.lastTimestamp | tail -20

# Ingress and certificate.
kubectl -n tradexa get ingress
kubectl -n tradexa describe ingress tradexa-hub | tail -20
```

If the pods are healthy but the site is not reachable, the problem is between
the ingress controller and the Service — check the NetworkPolicy first, since
`allow-ingress-to-web` matches on the `ingress-nginx` namespace label and a
controller installed elsewhere will be silently denied.

Roll back a bad deploy:

```bash
kubectl -n tradexa rollout undo deploy/tradexa-hub-web
kubectl -n tradexa rollout status deploy/tradexa-hub-web
```

---

## elevated-error-rate

**Alert:** `HubHighErrorRate` · critical

```bash
# Which routes?
curl -s $HUB/metrics | grep 'hub_http_requests_total.*status="5'

# The actual exceptions.
kubectl -n tradexa logs -l app.kubernetes.io/name=tradexa-hub --tail=1000 \
  | jq -r 'select(.level=="ERROR") | "\(.timestamp) \(.path) \(.message)"' | sort | uniq -c | sort -rn
```

If it started at a deploy, roll back first and diagnose from the logs
afterwards. Recovery beats understanding.

---

## high-latency

**Alert:** `HubHighLatency` · warning

```bash
# Slowest routes.
curl -s $HUB/metrics | grep hub_http_request_duration_seconds_bucket

# Saturation: a rising floor with flat request rate means requests are queuing.
curl -s $HUB/metrics | grep hub_http_requests_in_flight

# Slow requests are logged at WARNING with their duration.
kubectl -n tradexa logs -l app.kubernetes.io/component=web --tail=2000 \
  | jq -r 'select(.duration_ms > 2000) | "\(.duration_ms)ms \(.path)"' | sort -rn | head
```

If tracing is enabled, open the trace for a slow request — outbound calls are
instrumented, so the exchange or Supabase hop shows up directly.

---

## readiness-failing

**Alert:** `HubNotReady` · warning

Readiness names the failing dependency:

```bash
kubectl -n tradexa exec deploy/tradexa-hub-web -- \
  python -c "import urllib.request,json;print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read()),indent=2))"
```

- `data_dir` — the volume is full or mounted read-only. Check `kubectl exec -- df -h /data`.
- `database` — the SQLite store is unreadable. See [Disaster Recovery](DISASTER_RECOVERY.md).
- `engine` — see [engine-not-running](#engine-not-running).

A pod stuck `not_ready` after a rollout is usually still draining; that clears
on its own.

---

## engine-errors

**Alert:** `HubEngineErrors` · warning

```bash
curl -s $HUB/metrics | grep hub_engine_errors_total
kubectl -n tradexa logs -l app.kubernetes.io/component=engine --tail=500 \
  | jq -r 'select(.level=="ERROR" or .level=="WARNING") | .message' | sort | uniq -c | sort -rn
```

`stage="fetch"` means market data. Anything else is worth reading the traceback
for. The engine is designed to survive a fetch hiccup and continue, so a steady
low rate is tolerable; a rising rate is not.

---

## risk-veto-surge

**Alert:** `HubRiskVetoSurge` · info. Never page on this.

The risk gates are rejecting more than usual. That is the system working —
selectivity is the product. Worth a look during working hours:

```bash
# Which gate is rejecting?
curl -s $HUB/metrics | grep hub_risk_vetoes_total
```

A surge concentrated in one gate (`daily_loss`, `max_drawdown`, `controls`)
usually means a guard has engaged and is holding. Confirm that is intended
rather than a misconfigured threshold.

---

## auth-failure-spike

**Alert:** `HubAuthFailureSpike` · warning

```bash
curl -s $HUB/metrics | grep hub_auth_failures_total
kubectl -n tradexa logs -l app.kubernetes.io/component=web --tail=5000 \
  | jq -r 'select(.status==401) | .client_ip' | sort | uniq -c | sort -rn | head
```

Concentrated on a few IPs → credential stuffing; block at the ingress. Spread
widely, or coinciding with a deploy → a client is wedged with a stale secret.

If credentials may be compromised, rotate immediately:

```bash
kubectl -n tradexa create secret generic tradexa-hub-secrets \
  --from-literal=HUB_SECRET="$(openssl rand -hex 32)" ... \
  --dry-run=client -o yaml | kubectl apply -f -
# The Secret name carries no content hash, so pods must be restarted by hand.
kubectl -n tradexa rollout restart deploy/tradexa-hub-web statefulset/tradexa-hub-engine
```

Rotating `HUB_SECRET` invalidates every session — everyone is signed out. That
is the intended effect.

---

## rate-limit-saturated

**Alert:** `HubRateLimitSaturated` · warning

```bash
curl -s $HUB/metrics | grep hub_rate_limit_rejections_total
```

`scope="auth"` is login brute force; `scope="webhook"` is usually a TradingView
alert loop. If real users are being caught, raise the limit:

```bash
kubectl -n tradexa set env deploy/tradexa-hub-web HUB_RL_AUTH_MAX=30
```

---

## Emergency: stop trading now

The fastest safe halt, in order of decreasing speed:

```bash
# 1. Kill switch via the API (instant, keeps the service up).
curl -X POST $HUB/control/stop -H "x-webhook-secret: $HUB_API_KEY"

# 2. Stop the engine, keep the site serving.
kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=0

# 3. Disable the engine across restarts.
kubectl -n tradexa set env statefulset/tradexa-hub-engine HUB_AUTO_ENGINE=0
```

Option 1 leaves positions open but stops new entries. None of these closes
existing positions — do that deliberately through the dashboard.
