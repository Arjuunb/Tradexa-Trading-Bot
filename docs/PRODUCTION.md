# Production Deployment

How this system is built, deployed and operated. For incident response see
[RUNBOOK.md](RUNBOOK.md); for backups and restores see
[DISASTER_RECOVERY.md](DISASTER_RECOVERY.md).

## The one thing to understand first

**Exactly one trading engine may run at a time.**

Everything unusual about this deployment follows from that. Two engines against
one account do not share the work — they duplicate it. The same signal is
evaluated twice, two orders are placed, and real exposure is double what the
risk engine believes. It is not a degraded service; it is a correctness failure
with money attached.

The application was originally a single process that both served HTTP and ran
the engine, with six singleton workers starting at *import* time. Running two
copies of that process was never safe. `HUB_ROLE` splits it:

| `HUB_ROLE` | Serves HTTP | Runs engine, watchdog, monitor, daily tasks | Replicas |
|---|---|---|---|
| `all` *(default)* | yes | yes | **1** |
| `web` | yes | no | any |
| `engine` | health/metrics only | yes | **1** |

`all` is the default so every existing deployment — Render, `docker run`, local
`uvicorn` — behaves exactly as it always has. Nothing changes until you opt in.

Three independent layers enforce the single engine:

1. **Role.** Web replicas start no workers at all (`ops/runtime.py`). An
   unrecognised `HUB_ROLE` raises at import rather than falling back to `all` —
   a crash loop is far cheaper than silent double-trading.
2. **Scheduling.** The engine is a StatefulSet of one. Unlike a Deployment,
   which may briefly run old and new pods together during a rollout, a
   StatefulSet terminates the old pod before creating its replacement.
3. **A lease.** The engine takes a renewable lease before trading
   (`ops/singleton.py`). A process that cannot get it stays up as a warm
   standby and promotes itself if the leader disappears. This is the layer that
   catches what humans actually do: scaling something "just to see".

CI enforces 1 and 2 mechanically (`deploy/scripts/validate_manifests.py`), and
`HubMultipleEnginesRunning` pages if the invariant is ever violated at runtime.

## <a id="scaling-the-web-tier"></a>Scaling the web tier

**Read this before raising `replicas` above 1.**

The hub keeps its state in SQLite files on a shared volume. The engine is the
only writer of *trading* state, which is what makes the split topology safe. The
web tier, however, still writes **user accounts and settings**. Two web replicas
with independent state means a user can sign up on one pod and not exist on the
other — intermittently, depending on which replica the load balancer picks.

So the base ships `replicas: 1` for the web tier. That is a property of the
application's storage, not a limitation of the manifests.

To scale it safely, remove the shared-state problem first:

1. **Set `SUPABASE_URL` and `SUPABASE_KEY`.** The app already mirrors settings
   and the ledger there. This covers most of it.
2. **Migrate the account store (`hub.db`) to Postgres.** This is the remaining
   work, and it is a code change, not a configuration change.

Once both are done, `overlays/production` raises the web tier to 3 and enables
the HPA. Until then, treat `replicas > 1` as a deliberate, tested decision.

Splitting the roles is worth it even at one replica each: a code deploy now
rolls the web tier **without stopping the trading engine**, so shipping a CSS
fix no longer interrupts signal evaluation.

## Layout

```
deploy/
  docker/docker-compose.yml       production-shaped local stack
  k8s/base/                       workloads, services, policies
  k8s/overlays/{staging,production}
  observability/                  Prometheus, Grafana, OTel, Tempo
  scripts/                        generators, validators, smoke test
automation-hub/ops/               logging, metrics, tracing, health, lease
docs/                             this, RUNBOOK, DISASTER_RECOVERY
```

## Local

```bash
docker compose -f deploy/docker/docker-compose.yml up --build
```

Brings up the web tier, the engine, an OTel collector, Prometheus, Tempo and
Grafana — the real topology, on one machine.

- App — http://localhost:8000
- Grafana — http://localhost:3000 (anonymous viewer; admin / admin)
- Prometheus — http://localhost:9090

To watch the singleton guarantee hold:

```bash
docker compose -f deploy/docker/docker-compose.yml up --scale hub-web=3
```

Three web replicas, still one engine. `sum(hub_engine_running)` stays at 1.

## Kubernetes

Prerequisites: a ReadWriteMany StorageClass (both roles mount one volume), an
ingress controller, cert-manager, and a CNI that enforces NetworkPolicy — Calico,
Cilium or a managed equivalent. On a CNI that ignores NetworkPolicy the objects
apply cleanly and enforce nothing, so verify with a denied-connection test
rather than by reading `kubectl get`.

```bash
# 1. Secrets — never committed. See deploy/k8s/base/secret.example.yaml.
kubectl create namespace tradexa
kubectl -n tradexa create secret generic tradexa-hub-secrets \
  --from-literal=HUB_SECRET="$(openssl rand -hex 32)" \
  --from-literal=HUB_USERNAME=admin \
  --from-literal=HUB_PASSWORD="$(openssl rand -base64 24)" \
  --from-literal=HUB_WEBHOOK_SECRET="$(openssl rand -hex 32)" \
  --from-literal=HUB_API_KEY="$(openssl rand -hex 32)" \
  --from-literal=HUB_SCOPE_WEBHOOK=1

# 2. Deploy.
kubectl apply -k deploy/k8s/overlays/staging
kubectl apply -k deploy/k8s/overlays/production

# 3. Verify.
kubectl -n tradexa rollout status deploy/tradexa-hub-web
kubectl -n tradexa rollout status statefulset/tradexa-hub-engine
./deploy/scripts/smoke_test.sh https://www.trade-logx.com
```

For a real secrets workflow use External Secrets
(`deploy/k8s/base/externalsecret.yaml`) rather than `kubectl create secret`.

## Configuration

Non-secret values live in `deploy/k8s/base/config.env` and are rendered by
`configMapGenerator`, which appends a content hash to the ConfigMap name. That
hash is what makes a config change actually take effect — editing a plain
ConfigMap updates the mounted values but restarts nothing, so the change looks
applied while every pod carries on with the old settings.

The Secret is *not* generated and carries no hash, so **rotating a credential
does not roll the pods**. Follow a rotation with:

```bash
kubectl -n tradexa rollout restart deploy/tradexa-hub-web statefulset/tradexa-hub-engine
```

Variables introduced by this work:

| Variable | Default | Purpose |
|---|---|---|
| `HUB_ROLE` | `all` | `all` \| `web` \| `engine` |
| `HUB_SINGLETON_LEASE` | on for `engine` | Lease-gate the engine |
| `HUB_LEASE_TTL_S` | `60` | Failover window |
| `HUB_LOG_FORMAT` | `json` | `json` \| `text` |
| `HUB_LOG_LEVEL` | `INFO` | Root log level |
| `HUB_LOG_CAPTURE_PRINT` | `1` | Route `print()` through the logger |
| `HUB_ENV` | `development` | Tags logs, metrics and traces |
| `HUB_METRICS_TOKEN` | unset | Bearer token for `/metrics` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Tracing off unless set |
| `HUB_TRACE_SAMPLE` | `1.0` | Trace sample ratio |
| `HUB_BACKUP_S3_BUCKET` | unset | Offsite backups |

## Observability

**Logs** are one JSON object per line, carrying `service`, `env`, `role`,
`instance`, and — inside a request — `request_id`, `trace_id`, `span_id`. The
app's several hundred existing `print()` calls are routed through the logger by
a stdout bridge, so they are structured too without rewriting the trading code.

**Metrics** are at `/metrics`. HTTP paths are recorded as route templates
(`/bots/{bot_id}`, never `/bots/7f3a`) because a label taken from user input is
unbounded cardinality, and unbounded cardinality is how a Prometheus server runs
out of memory.

Series worth knowing:

| Metric | Why it matters |
|---|---|
| `hub_engine_running` | Must sum to exactly 1 |
| `hub_engine_leader` | Which instance holds the lease |
| `hub_engine_last_cycle_timestamp_seconds` | Distinguishes a quiet market from a wedged thread |
| `hub_trade_decisions_total` | Accepted vs rejected |
| `hub_risk_vetoes_total` | Which gate rejected, by stage |
| `hub_backup_last_success_timestamp_seconds` | Backup freshness |

**Traces** are off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The app exports
to a collector rather than to a backend directly, so swapping Tempo for a vendor
is a config change and a restart.

**Alerts** live in `deploy/observability/prometheus/rules/hub-alerts.yml` — one
source of truth, generated into the PrometheusRule CRD by
`deploy/scripts/gen_prometheusrule.py`, with CI failing on drift. Every alert
carries a `runbook` annotation.

## CI/CD

**CI** (`.github/workflows/ci.yml`) — tests on 3 Python versions, lint, manifest
validation, and an image job that builds the container, boots it, checks all
three probes, confirms it runs as non-root, waits for the Docker healthcheck,
and asserts every log line parses as JSON. Building proves it compiles; only
running it proves it starts.

**CD** (`.github/workflows/cd.yml`) — builds once, then refers to the image by
**digest** everywhere. Tags move; digests do not, and deploying by tag is how
staging and production end up running different bytes under the same name. The
image is scanned (Trivy), signed (cosign, keyless via OIDC) and shipped with an
SBOM. Staging deploys automatically; production requires an environment approval,
takes a pre-deploy backup, smoke-tests, verifies exactly one engine pod is
running, and rolls back on failure.

Cluster deployment is opt-in: set the repository variable `K8S_DEPLOY_ENABLED`
to `true` and provide `KUBE_CONFIG_STAGING` / `KUBE_CONFIG_PRODUCTION`. Without
them the build, scan and sign steps still run and the deploy jobs skip, so the
workflow is useful immediately rather than permanently red.

**Security** (`.github/workflows/security.yml`) — weekly and on PR: dependency
audit, secret scanning across history, IaC scanning, CodeQL, and a check that no
real credential has been committed into `deploy/`.

## Security posture

Containers run as uid 10001 with a read-only root filesystem, all capabilities
dropped, no privilege escalation, `RuntimeDefault` seccomp, and no mounted
Kubernetes API token — the app never calls the API, so there is nothing to
mount. The namespace enforces the `restricted` Pod Security Admission profile,
so a future pod that does not meet this bar is rejected at admission rather
than caught in review.

Networking is default-deny in both directions. Egress to the internet excludes
RFC1918 and `169.254.0.0/16` — that last one is the cloud metadata endpoint that
hands out node IAM credentials to anything that asks, and excluding it is the
difference between an SSRF being annoying and being an account compromise.

Rate limiting runs at both layers on purpose: the ingress limiter is cheap and
distributed and drops floods before they reach Python; the application limiter
is per-route and knows what it is protecting, so it can be strict on login
without throttling normal browsing. Neither subsumes the other.

The app refuses to boot with a default `HUB_SECRET` on a cloud host, because a
known session-signing key makes cookie forgery trivial.

## Render

Unaffected. `render.yaml` still deploys the same image with `HUB_ROLE=all`,
which is the behaviour it has always had. The Kubernetes manifests are an
addition, not a migration — nothing here changes the existing deployment.
