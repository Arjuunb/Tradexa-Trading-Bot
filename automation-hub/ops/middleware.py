"""Per-request observability: correlation id, metrics, access log.

Installed as the outermost HTTP middleware so it sees the true status and the
true latency, including time spent in the auth and security-header middleware
below it.

Two decisions worth stating, because both are load-bearing:

* **Paths are recorded as route templates.** ``/bots/{bot_id}``, never
  ``/bots/7f3a``. A label whose value comes from user input is unbounded
  cardinality, and unbounded cardinality is how a Prometheus server runs out of
  memory. Unmatched paths collapse to a single ``__unmatched__`` series, which
  also means a vulnerability scanner spraying random URLs cannot create a
  million time series.

* **Probes are counted but not logged.** Kubernetes hits liveness and readiness
  every few seconds forever. Logging those lines buries real traffic at a ratio
  of roughly a hundred to one and costs real money in a hosted log backend. The
  metrics still record them, so probe failures remain visible and alertable.
"""
from __future__ import annotations

import time
import uuid

from ops import metrics
from ops.log import get_logger, request_id_var

_log = get_logger("access")

# Not logged (still measured). Health and metrics only.
_QUIET_PATHS = frozenset({
    "/health", "/health/live", "/health/ready", "/health/startup", "/metrics",
})

REQUEST_ID_HEADER = "X-Request-ID"


def _route_template(request) -> str:
    """The matched route's template, or a single bucket for everything else."""
    route = request.scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    return template or "__unmatched__"


def install(app) -> None:
    """Attach the middleware. Call this LAST among add_middleware/@middleware
    registrations — Starlette applies them in reverse, so the one registered
    last runs first and therefore wraps all the others."""

    @app.middleware("http")
    async def _observe(request, call_next):  # noqa: ANN001, ANN202
        # Honour an inbound correlation id so a request keeps one identity
        # across the proxy, this service and anything it calls. Trim it: the
        # header is attacker-controlled and ends up in every log line.
        incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
        request_id = incoming[:64] if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        start = time.perf_counter()
        metrics.http_in_flight.inc()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception:
            # An unhandled exception still gets counted as a 500 before it
            # propagates to Starlette's handler — otherwise the failures that
            # matter most are the ones missing from the dashboard.
            _log.exception("unhandled error", extra={
                "method": request.method, "path": request.url.path,
            })
            raise
        finally:
            elapsed = time.perf_counter() - start
            metrics.http_in_flight.dec()
            path = _route_template(request)
            metrics.record_request(request.method, path, status, elapsed)

            if request.url.path not in _QUIET_PATHS:
                # Slow or failing requests deserve a level an alert can filter on.
                level = _log.warning if (status >= 500 or elapsed > 5.0) else _log.info
                level("request", extra={
                    "method": request.method,
                    "path": path,
                    "raw_path": request.url.path,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                    "client_ip": _client_ip(request),
                    "user_agent": request.headers.get("user-agent", "")[:200],
                })
            request_id_var.reset(token)


def _client_ip(request) -> str:
    """First hop of X-Forwarded-For, matching how app.py resolves the client
    behind Render's and the ingress controller's proxies."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
