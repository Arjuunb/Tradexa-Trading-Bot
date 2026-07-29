"""The error taxonomy.

Before this module the entire codebase defined exactly one custom exception
(``services.broker.BrokerError``); everything else raised bare ``Exception`` or
was swallowed by ``except Exception``. That has two costs in a trading system:
a caller cannot tell a recoverable feed hiccup from a configuration mistake, so
it either retries things that will never succeed or aborts on things it could
have ridden out — and a broad ``except`` silently absorbs genuine bugs.

Every exception here carries structured ``context`` rather than only a message,
so a handler can branch on facts (which symbol, which broker, which limit) and
a log line can be queried later instead of grepped.

The hierarchy is deliberately shallow. Two questions decide a handler's
behaviour, and the type answers both:

    is it retryable?   -> ``TransientError`` subclasses say yes
    whose fault is it? -> ``ConfigurationError`` means stop and fix the config

``TradexaError`` is the single root, so ``except TradexaError`` catches
everything this system raises without also swallowing ``KeyboardInterrupt``,
``MemoryError``, or a typo's ``AttributeError``.
"""
from __future__ import annotations

from typing import Any, Optional


class TradexaError(Exception):
    """Root of every error this system raises deliberately.

    ``context`` holds the facts a handler or a log query needs. Keep it to
    plain, serialisable values — never a live broker handle or an open
    connection, both because logs must stay printable and because an exception
    can outlive the object it captured.
    """

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    def __str__(self) -> str:
        if not self.context:
            return self.message
        detail = " ".join(f"{k}={v!r}" for k, v in sorted(self.context.items()))
        return f"{self.message} ({detail})"

    def as_dict(self) -> dict[str, Any]:
        """Log/serialise form. Used by structured logging and error responses."""
        return {"error": type(self).__name__, "message": self.message,
                "retryable": self.retryable, **self.context}

    #: Whether a caller may sensibly retry the same operation unchanged.
    retryable: bool = False


class TransientError(TradexaError):
    """A failure that may succeed on retry — a timeout, a rate limit, a blip.

    Separated from permanent failures because retry policy is the single most
    consequential branch in a live trading loop: retrying a permanent failure
    burns the rate limit, and aborting a transient one drops a fill.
    """

    retryable = True


# ── configuration ───────────────────────────────────────────────────────────
class ConfigurationError(TradexaError):
    """The system is misconfigured. Never retryable — retrying a bad API key or
    an impossible risk limit just fails again more expensively."""


# ── market data ─────────────────────────────────────────────────────────────
class DataFeedError(TradexaError):
    """Market data could not be produced, and not because of connectivity."""


class ExchangeConnectionError(TransientError):
    """Could not reach the exchange. Transient by default: exchanges rate-limit,
    time out and return 5xx routinely, and a live loop must survive that."""


class InsufficientDataError(DataFeedError):
    """Fewer bars than the calculation needs.

    Its own type because the correct response is specific: warm up longer or
    widen the range — not retry, and not abort the bot.
    """


# ── strategy ────────────────────────────────────────────────────────────────
class StrategyError(TradexaError):
    """A strategy failed to evaluate."""


class UnsupportedCapabilityError(StrategyError):
    """The strategy asked for something the engine cannot express.

    Raised rather than silently ignored: a rule the engine drops is a strategy
    the user never described, and its backtest would be of a different system.
    """


# ── risk ────────────────────────────────────────────────────────────────────
class RiskError(TradexaError):
    """Risk logic could not complete."""


class RiskRejection(RiskError):
    """A trade was refused by a risk rule. Not a fault — the guard working.

    Distinct from ``RiskError`` so callers can count rejections as normal
    operation while still alerting on genuine risk-engine failures.
    """

    def __init__(self, message: str, *, rule: str, **context: Any) -> None:
        super().__init__(message, rule=rule, **context)
        self.rule = rule


class KillSwitchEngaged(RiskError):
    """Trading is halted by a circuit breaker. Entries must not be attempted."""


# ── execution ───────────────────────────────────────────────────────────────
class ExecutionError(TradexaError):
    """An order could not be placed, amended or cancelled."""


class BrokerError(ExecutionError):
    """The broker rejected or failed the request."""


class OrderRejected(ExecutionError):
    """The venue refused the order — bad size, bad price, insufficient margin."""


class InsufficientFundsError(ExecutionError):
    """Not enough buying power. Permanent for this order at this size."""


# ── portfolio & storage ─────────────────────────────────────────────────────
class PortfolioError(TradexaError):
    """Portfolio state is inconsistent or could not be computed."""


class StorageError(TradexaError):
    """Persistence failed."""


__all__ = [
    "TradexaError", "TransientError",
    "ConfigurationError",
    "DataFeedError", "ExchangeConnectionError", "InsufficientDataError",
    "StrategyError", "UnsupportedCapabilityError",
    "RiskError", "RiskRejection", "KillSwitchEngaged",
    "ExecutionError", "BrokerError", "OrderRejected", "InsufficientFundsError",
    "PortfolioError", "StorageError",
]
