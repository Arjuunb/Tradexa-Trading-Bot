"""Who this process is, and what it is allowed to do.

The hub started life as a single process that both served HTTP and ran the
autonomous trading engine. That is fine on one host and actively dangerous on
several: the engine, the watchdog, the daily-report scheduler and the monitor
agent are all singletons that start at *import* time, so a second replica does
not share the work — it duplicates it. Two engines place two orders for the
same signal against the same paper account.

``HUB_ROLE`` splits those responsibilities so the deployment can scale the part
that is safe to scale:

    all     both jobs in one process. The default, and exactly what every
            existing single-instance deployment (Render, docker run, local
            uvicorn) has always done. Nothing changes unless you opt in.
    web     serve HTTP only. Safe to run at any replica count.
    engine  run the singleton workers. Must run exactly once — see
            ops/singleton.py for the lease that enforces it, and the engine
            StatefulSet in deploy/k8s/base for the scheduling guarantee.

An unrecognised value raises instead of falling back. A typo that silently
resolved to "all" would start a second trading engine, and a crash-looping pod
is a far cheaper failure than duplicate order flow.
"""
from __future__ import annotations

import os
import socket
import uuid

ROLE_ALL = "all"
ROLE_WEB = "web"
ROLE_ENGINE = "engine"
VALID_ROLES = (ROLE_ALL, ROLE_WEB, ROLE_ENGINE)

SERVICE_NAME = "tradexa-hub"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def role() -> str:
    """The role this process is running as. Read live from the environment so
    tests can flip it with monkeypatch without reimporting the module."""
    raw = _env("HUB_ROLE", ROLE_ALL).lower()
    if raw not in VALID_ROLES:
        raise RuntimeError(
            f"HUB_ROLE={raw!r} is not a valid role. Expected one of {', '.join(VALID_ROLES)}. "
            "Refusing to start: guessing here risks running a second trading engine."
        )
    return raw


def runs_workers() -> bool:
    """True when this process owns the singleton background workers — the
    autonomous engine, watchdog, monitor agent and daily tasks."""
    return role() in (ROLE_ALL, ROLE_ENGINE)


def serves_ui() -> bool:
    """True when this process serves the public site and dashboard. The engine
    role still serves /health and /metrics so it stays observable and probeable;
    it just does not carry user traffic."""
    return role() in (ROLE_ALL, ROLE_WEB)


def under_test() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def environment() -> str:
    """Deployment environment name — drives log/trace tagging and dashboards."""
    return _env("HUB_ENV") or _env("ENVIRONMENT") or "development"


def version() -> str:
    return _env("HUB_VERSION") or _env("APP_VERSION") or "0.0.0-dev"


def commit() -> str:
    """Build commit. Render injects RENDER_GIT_COMMIT; the Docker build and CI
    pass GIT_COMMIT. Matches what ``app._deploy_info()`` already reports."""
    return _env("RENDER_GIT_COMMIT") or _env("GIT_COMMIT")


_INSTANCE_ID: str | None = None


def instance_id() -> str:
    """A stable per-process identifier, used as the lease owner and as
    ``service.instance.id`` on traces and metrics.

    In Kubernetes HOSTNAME is the pod name, which is what an operator will
    recognise in a dashboard. The random suffix disambiguates two processes on
    one host (a local ``all`` process next to a container, say) so a lease
    holder is never ambiguous.
    """
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        host = _env("HOSTNAME") or socket.gethostname() or "unknown"
        _INSTANCE_ID = f"{host}-{uuid.uuid4().hex[:8]}"
    return _INSTANCE_ID


def resource_attributes() -> dict:
    """OpenTelemetry resource attributes, reused verbatim as structured-log
    fields so a log line and a span carry identical identity."""
    return {
        "service.name": SERVICE_NAME,
        "service.version": version(),
        "service.instance.id": instance_id(),
        "deployment.environment": environment(),
        "hub.role": role(),
    }
