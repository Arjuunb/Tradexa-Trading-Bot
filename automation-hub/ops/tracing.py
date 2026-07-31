"""OpenTelemetry tracing, exported over OTLP/HTTP.

Entirely opt-in: with no endpoint configured this module does nothing and costs
nothing, so local development and the existing Render deployment are unaffected.
Set ``OTEL_EXPORTER_OTLP_ENDPOINT`` (the collector in deploy/observability, or
any vendor endpoint) and traces start flowing.

Spans carry the same resource attributes that structured logs carry as fields,
and ``ops.log`` stamps ``trace_id``/``span_id`` onto every record emitted
inside a span. That is the whole point of doing both: a slow request in a
dashboard links to its trace, and the trace links back to the log lines the
handler produced.
"""
from __future__ import annotations

import logging
import os

from ops import runtime

_log = logging.getLogger("hub.tracing")
_configured = False

# Probes and scrapes would otherwise dominate the trace volume — Kubernetes
# hits liveness, readiness and /metrics on a fixed interval forever, and none of
# those spans has ever helped anyone debug anything.
_EXCLUDED = "health,health/live,health/ready,health/startup,metrics"


def endpoint() -> str:
    return (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            or os.environ.get("HUB_OTLP_ENDPOINT", "")).strip()


def enabled() -> bool:
    return bool(endpoint())


def configure_tracing(app=None) -> bool:
    """Set up the tracer provider and instrument FastAPI.

    Returns True when tracing is live. Never raises: a telemetry
    misconfiguration must not stop the trading service from booting, so every
    failure path here logs and returns False.
    """
    global _configured
    if _configured or not enabled():
        return _configured

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError:
        _log.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the OpenTelemetry SDK is not "
            "installed — tracing stays off. Install opentelemetry-sdk and "
            "opentelemetry-exporter-otlp-proto-http to enable it.")
        return False

    try:
        # ParentBased keeps a trace intact end to end: once an upstream service
        # has decided to sample a request, every downstream span joins it rather
        # than each service rolling its own dice and producing broken traces.
        ratio = float(os.environ.get("HUB_TRACE_SAMPLE", "1.0"))
        provider = TracerProvider(
            resource=Resource.create(runtime.resource_attributes()),
            sampler=ParentBased(root=TraceIdRatioBased(max(0.0, min(1.0, ratio)))),
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)

        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app, excluded_urls=_EXCLUDED)

        # Outbound HTTP is where this service actually spends its time —
        # exchange REST calls, the sentiment feed, Supabase. Without client
        # spans a slow trace is a flat bar with no explanation.
        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor

            RequestsInstrumentor().instrument()
        except ImportError:
            _log.debug("requests instrumentation unavailable; outbound calls untraced")

        _configured = True
        _log.info("tracing enabled", extra={"otlp_endpoint": endpoint(), "sample_ratio": ratio})
        return True
    except Exception:  # noqa: BLE001
        _log.warning("tracing setup failed; continuing without traces", exc_info=True)
        return False


def shutdown() -> None:
    """Flush buffered spans on the way out. Without this the last few seconds
    before a pod terminates — often the interesting ones — are lost in the
    batch processor's queue."""
    if not _configured:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:  # noqa: BLE001
        _log.debug("tracer shutdown failed", exc_info=True)
