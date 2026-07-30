"""Engine strategies.

``SupportResistanceRejection`` is re-exported **lazily**, and that is
load-bearing rather than a style choice.

It is now a plugin, so it imports ``tradexa.strategy``, whose ``BaseStrategy``
in turn subclasses ``bot.strategies.base.Strategy``. Importing it eagerly here
made that a cycle: importing ``tradexa.strategy`` reached
``bot.strategies.base``, which ran this package's ``__init__``, which imported
the strategy, which imported the half-built ``tradexa.strategy`` and found no
``BaseStrategy`` in it yet.

Deferring to first attribute access breaks the cycle. ``from bot.strategies
import SupportResistanceRejection`` still works exactly as before, so the call
sites that do it — ``bot/cli.py``, ``bot/config.py``, ``api/index.py`` and the
tests — are unchanged.
"""
from bot.strategies.base import Strategy

__all__ = ["Strategy", "SupportResistanceRejection"]


def __getattr__(name: str):
    """PEP 562 module-level attribute access, for the lazy re-export."""
    if name == "SupportResistanceRejection":
        from bot.strategies.support_resistance import SupportResistanceRejection
        globals()[name] = SupportResistanceRejection   # imported once, then cached
        return SupportResistanceRejection
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """So ``dir(bot.strategies)`` still lists the lazy export."""
    return sorted(set(globals()) | set(__all__))
