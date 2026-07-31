"""Prometheus instrumentation.

Everything here degrades to a no-op when ``prometheus_client`` is not installed.
That is not defensiveness for its own sake: the hub's core is deliberately
stdlib-only, the package is declared in ``automation-hub/requirements.txt`` and
so is present in every container and CI run, but a developer running
``uvicorn app:app`` in a bare virtualenv should still get a working app rather
than an ImportError from a metrics import. ``/metrics`` reports the degraded
state honestly instead of pretending to serve an empty scrape.

Recording helpers are wrapped so an instrumentation bug can never propagate into
the trading path. A dropped metric is an inconvenience; an exception raised from
inside order handling because a label was the wrong type is an outage.

Metric naming follows the Prometheus conventions: ``_total`` for counters,
base units (seconds, not milliseconds), and labels kept to bounded sets. HTTP
paths are recorded as their *route template* (``/bots/{bot_id}``), never the raw
URL — one series per route instead of one per bot id.
"""
from __future__ import annotations

import logging
import time

from ops import runtime

_log = logging.getLogger("hub.metrics")

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in a bare env
    AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


class _Noop:
    """Stands in for a metric when prometheus_client is absent. Absorbs the
    whole fluent API (``.labels(...).inc()``) without error."""

    def labels(self, *a, **kw):  # noqa: ANN002, ANN003, ARG002
        return self

    def inc(self, *a, **kw):  # noqa: ANN002, ANN003, ARG002
        return None

    def dec(self, *a, **kw):  # noqa: ANN002, ANN003, ARG002
        return None

    def set(self, *a, **kw):  # noqa: ANN002, ANN003, ARG002
        return None

    def observe(self, *a, **kw):  # noqa: ANN002, ANN003, ARG002
        return None


def _metric(kind, name: str, doc: str, labels: tuple = (), **kw):
    """Create a collector, tolerating re-registration.

    The test suite imports ``app`` more than once in a session and module-level
    metric construction would otherwise raise "Duplicated timeseries in
    CollectorRegistry" on the second import, taking the whole app down with it.
    On collision we return the already-registered collector, which is the object
    the first import is holding anyway.
    """
    if not AVAILABLE:
        return _Noop()
    try:
        return kind(name, doc, labels, **kw) if labels else kind(name, doc, **kw)
    except ValueError:
        existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        if existing is not None:
            return existing
        _log.warning("metric %s could not be registered; using a no-op", name)
        return _Noop()


# Latency buckets tuned for this service rather than the library default. The
# hub serves cached dashboard fragments in single-digit milliseconds and does
# exchange round-trips in hundreds, so resolution is needed at both ends.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# ── build identity ──────────────────────────────────────────────────────────
# The classic info-metric pattern: a gauge fixed at 1 whose labels carry the
# metadata. Lets a dashboard join "which version served this" onto any series.
build_info = _metric(Gauge, "hub_build_info", "Build and runtime identity (always 1).",
                     ("version", "commit", "role", "env"))

# ── HTTP ────────────────────────────────────────────────────────────────────
http_requests = _metric(Counter, "hub_http_requests_total",
                        "HTTP requests by route template, method and status class.",
                        ("method", "path", "status"))
http_duration = _metric(Histogram, "hub_http_request_duration_seconds",
                        "HTTP request latency in seconds.",
                        ("method", "path"), buckets=_LATENCY_BUCKETS)
http_in_flight = _metric(Gauge, "hub_http_requests_in_flight",
                         "HTTP requests currently being served.")

# ── protection ──────────────────────────────────────────────────────────────
rate_limit_rejections = _metric(Counter, "hub_rate_limit_rejections_total",
                                "Requests rejected by the rate limiter, by policy scope.",
                                ("scope",))
auth_failures = _metric(Counter, "hub_auth_failures_total",
                        "Rejected authentication attempts, by reason.", ("reason",))

# ── trading engine ──────────────────────────────────────────────────────────
# engine_running is per-process; engine_leader says whether THIS process holds
# the singleton lease. Across a healthy deployment their sums must both be 1.
# An alert fires when either is not, because two of anything here means
# duplicate order flow.
engine_running = _metric(Gauge, "hub_engine_running",
                         "1 when the autonomous engine thread is alive in this process.")
engine_leader = _metric(Gauge, "hub_engine_leader",
                        "1 when this process holds the singleton engine lease.")
engine_cycles = _metric(Counter, "hub_engine_cycles_total",
                        "Completed engine evaluation cycles.")
engine_cycle_duration = _metric(Histogram, "hub_engine_cycle_duration_seconds",
                                "Duration of one engine evaluation cycle.",
                                buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60))
engine_last_cycle = _metric(Gauge, "hub_engine_last_cycle_timestamp_seconds",
                            "Unix timestamp of the last completed engine cycle.")
engine_errors = _metric(Counter, "hub_engine_errors_total",
                        "Errors raised inside the engine loop, by stage.", ("stage",))

# ── trading outcomes ────────────────────────────────────────────────────────
trades = _metric(Counter, "hub_trades_total", "Executed trades.", ("symbol", "side"))
decisions = _metric(Counter, "hub_trade_decisions_total",
                    "Trade decisions by outcome (accepted / rejected).", ("decision",))
risk_vetoes = _metric(Counter, "hub_risk_vetoes_total",
                      "Trades blocked by a risk gate, by which gate blocked them.",
                      ("reason",))
equity_value = _metric(Gauge, "hub_equity_value", "Current account equity.")
open_positions = _metric(Gauge, "hub_open_positions", "Currently open positions.")

# ── data freshness and durability ───────────────────────────────────────────
market_data_age = _metric(Gauge, "hub_market_data_age_seconds",
                          "Age of the newest candle held for a symbol.", ("symbol",))
backup_last_success = _metric(Gauge, "hub_backup_last_success_timestamp_seconds",
                              "Unix timestamp of the last successful backup.")
backup_failures = _metric(Counter, "hub_backup_failures_total", "Failed backup runs.")


def init() -> None:
    """Publish build identity. Safe to call more than once."""
    try:
        build_info.labels(
            version=runtime.version(), commit=runtime.commit() or "unknown",
            role=runtime.role(), env=runtime.environment(),
        ).set(1)
    except Exception:  # noqa: BLE001
        _log.debug("build_info not published", exc_info=True)


def _safe(fn):
    """Instrumentation must never raise into a caller. Wraps a recorder so a
    bad label or an arithmetic surprise is logged at debug and dropped."""

    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            _log.debug("metric %s failed", fn.__name__, exc_info=True)
            return None

    wrapper.__name__ = fn.__name__
    return wrapper


@_safe
def record_request(method: str, path: str, status: int, duration_s: float) -> None:
    http_requests.labels(method=method, path=path, status=str(status)).inc()
    http_duration.labels(method=method, path=path).observe(duration_s)


@_safe
def record_rate_limit(scope: str) -> None:
    rate_limit_rejections.labels(scope=scope).inc()


@_safe
def record_auth_failure(reason: str) -> None:
    auth_failures.labels(reason=reason).inc()


@_safe
def record_trade(symbol: str, side: str) -> None:
    trades.labels(symbol=symbol, side=str(side).lower()).inc()
    decisions.labels(decision="accepted").inc()


@_safe
def record_risk_veto(reason: str) -> None:
    risk_vetoes.labels(reason=reason).inc()
    decisions.labels(decision="rejected").inc()


@_safe
def set_equity(value: float) -> None:
    equity_value.set(float(value))


@_safe
def set_open_positions(n: int) -> None:
    open_positions.set(int(n))


@_safe
def set_engine_running(running: bool) -> None:
    engine_running.set(1 if running else 0)


@_safe
def set_engine_leader(is_leader: bool) -> None:
    engine_leader.set(1 if is_leader else 0)


@_safe
def record_engine_error(stage: str) -> None:
    engine_errors.labels(stage=stage).inc()


@_safe
def set_market_data_age(symbol: str, age_s: float) -> None:
    market_data_age.labels(symbol=symbol).set(float(age_s))


@_safe
def record_backup(ok: bool) -> None:
    if ok:
        backup_last_success.set(time.time())
    else:
        backup_failures.inc()


@_safe
def record_cycle(duration_s: float) -> None:
    """Record one completed engine evaluation pass.

    The timestamp gauge is the important one: it is what the "engine stalled"
    alert watches. A cycle *counter* alone cannot tell "idle because the market
    is quiet" from "the thread is wedged" — both look like a flat line — but
    ``time() - last_cycle`` distinguishes them exactly.
    """
    engine_cycles.inc()
    engine_cycle_duration.observe(duration_s)
    engine_last_cycle.set(time.time())


def render() -> tuple[bytes, str]:
    """The scrape payload and its content type."""
    if not AVAILABLE:
        return (
            b"# prometheus_client is not installed; no metrics are being collected.\n"
            b"# pip install prometheus-client to enable this endpoint.\n",
            "text/plain; charset=utf-8",
        )
    return generate_latest(), CONTENT_TYPE_LATEST
