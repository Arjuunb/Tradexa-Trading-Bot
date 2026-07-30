"""Catalog of available strategies and exchanges.

Still the single source of truth the UI and BotManager use to list options and
to construct concrete objects from a BotConfig's string keys — but no longer a
hand-maintained dictionary. ``STRATEGIES`` is now BUILT from the plugin
registry, which discovers strategies rather than being edited to include them.

What that changes in practice: adding a strategy used to mean editing this file
— an import line and a tuple, in the module that also decides how bots are
constructed. Now it means writing a file that declares its own ``StrategyMeta``
and putting it in the built-in package or the plugins directory. Nothing here
is touched.

**Only offerable strategies are listed here:** stable, not deprecated, and
constructible from a key plus a symbol. That keeps this dictionary exactly what
it has always been — ``ema``, ``rsi``, ``smc`` — while the other installed
strategies stay discoverable, documented, validated and backtestable through
``installed()`` and the strategies API. A strategy is promoted into the builder
by raising its own ``maturity``, which is still a change to the plugin rather
than to the engine.

One of them could not be listed here even if it were stable, and the
distinction is worth stating: ``custom`` takes a ``spec`` with no default, so
building it from a key and a symbol alone would raise. Offering an option the
builder crashes on is worse than not offering it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from tradexa.strategy import StrategyRegistry, UnknownStrategyError, discover_all

from strategies.base_strategy import HubStrategy

#: Where third-party strategy files are dropped. Overridable so a deployment can
#: point it at a mounted disk and keep installed plugins across restarts.
PLUGINS_DIR = Path(os.environ.get(
    "HUB_PLUGINS_DIR", str(Path(__file__).resolve().parents[1] / "plugins")))

#: Built-in strategies live in a real package. They go through the identical
#: registration path as a third-party plugin — built-in is a location, not a
#: privilege, so a bug in the plugin path shows up here immediately rather than
#: only for users.
BUILTIN_PACKAGE = "strategies"

_registry: Optional[StrategyRegistry] = None


def registry(*, refresh: bool = False) -> StrategyRegistry:
    """The installed strategies, discovered once and cached.

    Cached because discovery imports modules, and re-importing per request would
    re-run module-level code on a hot path. ``refresh=True`` is for tests and
    for an explicit "rescan the plugins directory".
    """
    global _registry
    if _registry is None or refresh:
        _registry = discover_all(packages=(BUILTIN_PACKAGE,),
                                 directories=(PLUGINS_DIR,),
                                 registry=StrategyRegistry())
        for err in _registry.errors:
            # Loud, but not fatal. A broken plugin must not stop the strategies
            # running live bots from loading — and it must not load silently
            # either, or the author's first clue is a strategy that never
            # appears anywhere.
            print(f"[plugins] {err['source']}: {err['error']}: {err['message']}",
                  flush=True)
    return _registry


def installed() -> tuple[type[HubStrategy], ...]:
    """Every discovered strategy, offerable or not."""
    return registry().all()


def discovery_errors() -> list[dict[str, str]]:
    """Plugins that failed to load, with the reason. Surfaced by the API."""
    return list(registry().errors)


def _catalog() -> dict[str, tuple[type[HubStrategy], str, bool]]:
    return {c.meta.key: (c, getattr(c, "label", None) or c.meta.name, True)
            for c in registry().offerable()}


class _StrategyCatalog(dict):
    """``STRATEGIES``, kept a dict so every existing call site is unchanged.

    ``app.py`` iterates it, ``bots/manager.py`` indexes it, ``services/regime.py``
    calls ``.get`` — all of which a plain dict supports and none of which needs
    to know the contents are discovered. A dict subclass rather than a function
    purely so those call sites do not change.
    """

    def refresh(self) -> "_StrategyCatalog":
        registry(refresh=True)
        self.clear()
        self.update(_catalog())
        return self


# key -> (class, human label, ready?)
STRATEGIES: _StrategyCatalog = _StrategyCatalog(_catalog())

# key -> (human label, asset class, ready?)
EXCHANGES: dict[str, tuple[str, str, bool]] = {
    "binance": ("Binance", "crypto", True),    # Phase 2 live wiring
    "bybit": ("Bybit", "crypto", False),
    "alpaca": ("Alpaca", "stocks", False),
}


def build_strategy(key: str, symbol: str, **params) -> HubStrategy:
    """Construct a strategy by key.

    Raises ``ValueError`` on an unknown key, as it always has. The registry's
    own ``UnknownStrategyError`` is a ``KeyError``, and call sites around here
    already catch ``ValueError`` from strategy constructors — changing the
    exception type would slip past those handlers as a 500.
    """
    try:
        return registry().build(key, symbol, **params)
    except UnknownStrategyError as exc:
        raise ValueError(f"unknown strategy {key!r}") from exc


def strategy_label(key: str) -> str:
    cls = registry().find(key)
    return (getattr(cls, "label", None) or cls.meta.name) if cls else key


def strategy_class(key: str) -> Optional[type[HubStrategy]]:
    return registry().find(key)


def describe_strategies() -> list[dict[str, Any]]:
    """Full plugin descriptions — metadata, version, parameters, optimisation
    grid, generated documentation — for every installed strategy."""
    return registry().describe()


def exchange_label(key: str) -> str:
    return EXCHANGES.get(key, (key, "", False))[0]
