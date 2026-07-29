"""Structured logging — the ``Logger`` port, implemented.

The system currently logs with f-strings: readable once, unqueryable forever.
``f"{sym}: live fetch failed ({e})"`` cannot answer "how many fetch failures on
BTCUSDT in the last hour?" without a regex that breaks the next time someone
edits the wording.

So a record here is an **event name plus fields**, never a pre-formatted
sentence:

    log.warning("feed.fetch_failed", symbol="BTCUSDT", exchange="kraken",
                error="timeout")

The event name is a stable identifier — `feed.fetch_failed` — and the fields
are data. Rewording is then a display change, not a break in every query built
on it.

Output is JSON when ``HUB_LOG_FORMAT=json`` (for a log aggregator) and aligned
key=value otherwise (for a human reading a terminal). Same record either way;
only the rendering differs.

This wraps the stdlib ``logging`` rather than replacing it, so existing
handlers, levels and the root configuration continue to apply — a logging layer
that bypasses the stdlib is one that cannot be silenced or redirected by the
operator running the process.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

#: Field names the record owns. A context key colliding with one of these
#: would overwrite the frame's own timestamp or severity, so they are prefixed
#: on collision rather than silently dropped or allowed to clobber.
#:
#: For that handling to be reachable at all, `event` is declared positional-only
#: (the `/` in each signature). Without it `log.info("evt", **{"event": "x"})`
#: raises TypeError before this module sees the call — and any caller splatting
#: a context dict that happens to contain "event" would crash rather than log.
_RESERVED = frozenset({"timestamp", "level", "event", "module", "duration_ms"})


def _json_default(value: Any) -> str:
    """Anything not natively serialisable becomes its repr rather than raising.

    A log call must never be the thing that breaks a trading loop. Losing
    fidelity on an odd value is a fair price for that guarantee.
    """
    return repr(value)


class StructuredLogger:
    """Emits structured records. Satisfies ``tradexa.core.interfaces.Logger``."""

    def __init__(self, module: str, *, logger: Optional[logging.Logger] = None,
                 fmt: Optional[str] = None) -> None:
        self.module = module
        self._log = logger or logging.getLogger(f"tradexa.{module}")
        # Read at construction, not per call — a format that changes between
        # two lines of the same run makes a log file unparseable.
        self._fmt = (fmt or os.environ.get("HUB_LOG_FORMAT", "text")).lower()

    # ------------------------------------------------------------- emitting
    def _record(self, level: str, event: str, context: dict[str, Any],
                duration_ms: Optional[float] = None) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "module": self.module,
            "event": event,
        }
        if duration_ms is not None:
            rec["duration_ms"] = round(duration_ms, 2)
        for key, value in context.items():
            rec[f"ctx_{key}" if key in _RESERVED else key] = value
        return rec

    def _render(self, rec: dict[str, Any]) -> str:
        if self._fmt == "json":
            return json.dumps(rec, default=_json_default, sort_keys=True)
        head = f"{rec['timestamp']} {rec['level']:<7} {rec['module']}.{rec['event']}"
        rest = {k: v for k, v in rec.items()
                if k not in ("timestamp", "level", "module", "event")}
        if not rest:
            return head
        body = " ".join(f"{k}={v!r}" for k, v in sorted(rest.items()))
        return f"{head}  {body}"

    def _emit(self, level: int, name: str, event: str,
              context: dict[str, Any], duration_ms: Optional[float] = None) -> None:
        rec = self._record(name, event, context, duration_ms)
        # `extra` keeps the structured dict available to any handler that wants
        # the fields rather than the rendered line.
        self._log.log(level, self._render(rec), extra={"structured": rec})

    def debug(self, event: str, /, **context: Any) -> None:
        self._emit(logging.DEBUG, "DEBUG", event, context)

    def info(self, event: str, /, **context: Any) -> None:
        self._emit(logging.INFO, "INFO", event, context)

    def warning(self, event: str, /, **context: Any) -> None:
        self._emit(logging.WARNING, "WARNING", event, context)

    def error(self, event: str, /, **context: Any) -> None:
        self._emit(logging.ERROR, "ERROR", event, context)

    def exception(self, event: str, exc: BaseException, /, **context: Any) -> None:
        """Log a caught exception, unpacking a ``TradexaError``'s structured
        context into fields rather than flattening it into the message."""
        payload = dict(context)
        as_dict = getattr(exc, "as_dict", None)
        if callable(as_dict):
            try:
                payload.update(as_dict())
            except Exception:  # noqa: BLE001 — never fail a log call
                payload["error"] = type(exc).__name__
        else:
            payload.setdefault("error", type(exc).__name__)
            payload.setdefault("message", str(exc))
        self._emit(logging.ERROR, "ERROR", event, payload)

    # -------------------------------------------------------------- timing
    @contextmanager
    def timed(self, event: str, /, **context: Any) -> Iterator[dict[str, Any]]:
        """Time a block and log its duration — once, on the way out.

        Yields a mutable dict so the block can attach facts discovered while
        running (how many bars were fetched, which source answered) to the same
        record. Two separate log lines for one operation cannot be joined
        without a correlation id nobody is issuing yet.

        On exception the duration is still logged, at ERROR, and the exception
        propagates. Timing that only records success hides exactly the slow
        path worth knowing about — a request that took 30 seconds and then
        failed.
        """
        extra: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield extra
        except Exception as exc:  # noqa: BLE001 — logged, then re-raised
            elapsed = (time.perf_counter() - started) * 1000
            self._emit(logging.ERROR, "ERROR", event,
                       {**context, **extra, "error": type(exc).__name__,
                        "message": str(exc)}, duration_ms=elapsed)
            raise
        else:
            elapsed = (time.perf_counter() - started) * 1000
            self._emit(logging.INFO, "INFO", event, {**context, **extra},
                       duration_ms=elapsed)


def get_logger(module: str) -> StructuredLogger:
    """Preferred entry point. One logger per module, named after it."""
    return StructuredLogger(module)


class NullLogger:
    """Accepts and discards. The default where logging is optional, so callers
    need no ``if self._log`` guard at every site."""

    def debug(self, event: str, /, **context: Any) -> None: return None
    def info(self, event: str, /, **context: Any) -> None: return None
    def warning(self, event: str, /, **context: Any) -> None: return None
    def error(self, event: str, /, **context: Any) -> None: return None
    def exception(self, event: str, exc: BaseException, /, **context: Any) -> None: return None

    @contextmanager
    def timed(self, event: str, /, **context: Any) -> Iterator[dict[str, Any]]:
        yield {}


__all__ = ["StructuredLogger", "NullLogger", "get_logger"]
