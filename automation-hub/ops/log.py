"""Structured (JSON) logging with request and trace correlation.

Three problems this solves, in order of how much they hurt in production:

1. **The hub logs with bare ``print()``** — several hundred call sites. Those
   lines are human-readable and machine-hostile: no level, no timestamp, no way
   to filter "errors in the last hour" in a log backend. Rewriting every call
   site would be a huge, risky diff across trading code, so instead
   ``install_print_bridge()`` re-points ``sys.stdout`` at the logger. Existing
   ``print()`` calls keep working and come out as structured records.

2. **Uvicorn logs in its own format**, so a deployment emitted two or three
   different shapes on one stream. ``configure_logging()`` strips uvicorn's
   handlers and lets its records propagate to the root logger instead.

3. **Nothing correlates.** A log line could not be tied to the request or the
   trace that produced it. Every record now carries ``request_id``, and when a
   span is active, ``trace_id``/``span_id`` in the hex form Grafana/Tempo/Jaeger
   expect — so "show me the logs for this trace" is a filter, not an
   archaeology exercise.

Format is JSON by default and switchable to plain text with ``HUB_LOG_FORMAT=text``
for local work, where a human is the consumer and jq is a nuisance.
"""
from __future__ import annotations

import contextvars
import datetime as _dt
import json
import logging
import os
import sys
import threading

from ops import runtime

# The request id for the task currently executing. A ContextVar (not a
# thread-local) because the app is async: one thread serves many concurrent
# requests, and only a ContextVar follows the await chain rather than the thread.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

# Kept so the log handler can write to the true stdout even after the print
# bridge has replaced sys.stdout. Without this the handler's own output would be
# captured by the bridge and fed back into the logger — infinite recursion on
# the first log line.
_REAL_STDOUT = sys.stdout

# LogRecord's own attributes. Anything on a record that is NOT in this set was
# put there by a caller via `extra=` and belongs in the JSON payload.
_RESERVED = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
})

_configured = False
_lock = threading.Lock()


def _trace_ids() -> tuple[str, str]:
    """Current trace/span id as 32- and 16-char hex, or empty strings.

    Imported lazily and defensively: tracing is optional, and logging must not
    acquire a hard dependency on the OpenTelemetry SDK being installed or
    initialised.
    """
    try:
        from opentelemetry import trace as _t

        ctx = _t.get_current_span().get_span_context()
        if not ctx.is_valid:
            return "", ""
        return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    except Exception:  # noqa: BLE001 — never let telemetry break a log line
        return "", ""


class JsonFormatter(logging.Formatter):
    """One JSON object per line, newline-delimited — the shape Loki, Datadog,
    CloudWatch and friends parse without a custom pipeline."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": runtime.SERVICE_NAME,
            "env": runtime.environment(),
            "role": _safe_role(),
            "instance": runtime.instance_id(),
        }
        if (v := runtime.version()) != "0.0.0-dev":
            payload["version"] = v
        if rid := request_id_var.get():
            payload["request_id"] = rid
        trace_id, span_id = _trace_ids()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        # default=str so a stray object in `extra=` degrades to its repr rather
        # than raising inside the logging machinery, which swallows the real
        # message and prints a formatter traceback instead.
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human format for local development. Keeps the correlation ids visible
    but out of the way."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        base = super().format(record)
        if rid := request_id_var.get():
            base += f"  [req {rid[:8]}]"
        return base


def _safe_role() -> str:
    """runtime.role() raises on an invalid HUB_ROLE. Logging must never be the
    thing that raises — the boot error itself needs to reach the operator."""
    try:
        return runtime.role()
    except RuntimeError:
        return "invalid"


class _StdoutBridge:
    """A file-like object that turns writes into log records.

    ``print()`` writes the text and the newline as separate calls, and a caller
    may write a partial line, so writes are buffered and flushed a line at a
    time. The re-entrancy guard matters: if anything inside the logging path
    were to print, this would recurse until the stack ran out.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._buf: list[str] = []
        self._local = threading.local()

    def write(self, data: str) -> int:
        if not data:
            return 0
        if getattr(self._local, "busy", False):
            return _REAL_STDOUT.write(data)
        self._buf.append(data)
        if "\n" in data:
            self.flush()
        return len(data)

    def flush(self) -> None:
        if not self._buf:
            return
        text = "".join(self._buf)
        self._buf = []
        if not text.endswith("\n"):
            # Hold the trailing partial line back until its newline arrives, so
            # a line assembled across several writes is logged as one record.
            head, sep, tail = text.rpartition("\n")
            if not sep:
                self._buf.append(text)
                return
            self._buf.append(tail)
            text = head
        self._local.busy = True
        try:
            for line in text.splitlines():
                if line.strip():
                    self._logger.info(line)
        finally:
            self._local.busy = False

    # Enough of the stream protocol to stand in for sys.stdout. Uvicorn and
    # click both probe isatty(); returning False also stops them emitting ANSI
    # colour codes into what is now a JSON stream.
    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return _REAL_STDOUT.fileno()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return getattr(_REAL_STDOUT, "encoding", "utf-8")


def install_print_bridge() -> None:
    """Route ``print()`` through the logger. Idempotent."""
    if isinstance(sys.stdout, _StdoutBridge):
        return
    sys.stdout = _StdoutBridge(logging.getLogger("hub.stdout"))


def configure_logging(*, force: bool = False) -> None:
    """Install the root handler. Call once, early in boot.

    Reads ``HUB_LOG_LEVEL`` (default INFO) and ``HUB_LOG_FORMAT``
    (``json``|``text``, default json). ``HUB_LOG_CAPTURE_PRINT=0`` opts out of
    the print bridge.
    """
    global _configured
    with _lock:
        if _configured and not force:
            return

        level = os.environ.get("HUB_LOG_LEVEL", "INFO").upper()
        fmt = os.environ.get("HUB_LOG_FORMAT", "json").lower()
        formatter = TextFormatter() if fmt == "text" else JsonFormatter()

        handler = logging.StreamHandler(_REAL_STDOUT)
        handler.setFormatter(formatter)

        root = logging.getLogger()
        for existing in list(root.handlers):
            root.removeHandler(existing)
        root.addHandler(handler)
        root.setLevel(getattr(logging, level, logging.INFO))

        # Uvicorn installs its own handlers at startup; leaving them attached
        # emits every access line twice, once per format. Clearing them and
        # letting the records propagate puts all output through one formatter.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
            lg = logging.getLogger(name)
            lg.handlers.clear()
            lg.propagate = True

        # Third-party libraries that are chatty at INFO and say nothing an
        # operator acts on. Their warnings and errors still come through.
        for noisy in ("httpx", "httpcore", "urllib3", "ccxt", "asyncio",
                      "opentelemetry.sdk.trace.export"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        capture = os.environ.get("HUB_LOG_CAPTURE_PRINT", "1").lower()
        if capture not in ("0", "false", "no", "off") and fmt != "text":
            install_print_bridge()

        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Logger for a hub module. Prefixed so a backend can select the app's own
    records apart from library output with one filter."""
    return logging.getLogger(name if name.startswith("hub") else f"hub.{name}")
