"""Where installed strategies live.

The registry is the thing that replaces a hand-maintained dictionary in the
trading engine. Adding a strategy used to mean editing that dictionary — an
import line and a tuple, in a file that also decides how bots are built. Now a
strategy declares its own key and the registry finds it.

Two rules make that safe rather than merely convenient.

**A duplicate key is an error, not a silent overwrite.** Two plugins claiming
``"ema"`` is a real situation once users install third-party strategies, and
last-import-wins would mean a bot's saved configuration quietly starts running
different code. The conflict is raised with both sources named.

**Registration validates the plugin.** A class that is not a ``BaseStrategy``,
has no key, or is still abstract is rejected at registration with a reason —
not at 3am when a bot tries to trade with it.
"""
from __future__ import annotations

import inspect
from typing import Any, Iterator, Optional

from tradexa.strategy.base import BaseStrategy


class StrategyRegistryError(Exception):
    """Base for every registration failure."""


class DuplicateStrategyError(StrategyRegistryError):
    def __init__(self, key: str, existing: str, incoming: str) -> None:
        self.key, self.existing, self.incoming = key, existing, incoming
        super().__init__(
            f"two strategies claim the key {key!r}: {existing} and {incoming}. "
            "Keys are how saved bot configurations find their code, so one of "
            "them must be renamed rather than silently winning.")


class InvalidStrategyError(StrategyRegistryError):
    pass


class UnknownStrategyError(StrategyRegistryError, KeyError):
    def __init__(self, key: str, known: tuple[str, ...]) -> None:
        self.key, self.known = key, known
        # KeyError reprs its argument, so the message is built once and passed
        # whole rather than assembled at each raise site.
        super().__init__(
            f"unknown strategy {key!r}. Installed: "
            f"{', '.join(known) if known else '(none)'}")


def _origin(cls: type) -> str:
    """Where a class came from, for a conflict message someone can act on."""
    try:
        return f"{cls.__module__} ({inspect.getfile(cls)})"
    except (TypeError, OSError):  # pragma: no cover - dynamic classes
        return cls.__module__


class StrategyRegistry:
    """A collection of installed strategy plugins.

    Instances rather than a module-level dict: a test needs its own registry,
    and a tenant may one day need a different set. ``default_registry()``
    provides the shared one for callers that just want "the installed
    strategies".
    """

    def __init__(self) -> None:
        self._by_key: dict[str, type[BaseStrategy]] = {}
        #: Discovery problems, kept rather than raised — see `discovery.py`.
        self.errors: list[dict[str, str]] = []

    # ---------------------------------------------------------------- write
    def register(self, cls: type[BaseStrategy], *, source: str = "",
                 replace: bool = False) -> type[BaseStrategy]:
        """Install one strategy class. Returns it, so this works as a decorator."""
        if not (isinstance(cls, type) and issubclass(cls, BaseStrategy)):
            raise InvalidStrategyError(
                f"{cls!r} does not inherit from BaseStrategy — the plugin "
                "contract (metadata, parameters, validation, docs) is what the "
                "registry, the UI and the optimiser all read")
        meta = getattr(cls, "meta", None)
        if meta is None or not getattr(meta, "key", ""):
            raise InvalidStrategyError(
                f"{cls.__qualname__} declares no meta.key — a strategy without "
                "a key cannot be referenced by a saved bot configuration")
        if meta.key == BaseStrategy.meta.key:
            raise InvalidStrategyError(
                f"{cls.__qualname__} still carries the base class's placeholder "
                f"meta (key={meta.key!r}) — declare its own StrategyMeta")
        if inspect.isabstract(cls):
            raise InvalidStrategyError(
                f"{cls.__qualname__} is abstract ("
                f"{', '.join(sorted(cls.__abstractmethods__))} unimplemented)")

        existing = self._by_key.get(meta.key)
        if existing is not None and not replace:
            if existing is cls:
                return cls          # idempotent: re-importing a module is not a conflict
            raise DuplicateStrategyError(meta.key, _origin(existing), _origin(cls))
        if source:
            # Stamped by the loader, never trusted from the author: a plugin
            # that could name its own origin could claim to be a built-in.
            # Plain setattr, not object.__setattr__ — the latter refuses a class
            # with a metaclass, and every BaseStrategy has ABCMeta.
            setattr(cls, "meta", _with_source(meta, source))
        self._by_key[meta.key] = cls
        return cls

    def unregister(self, key: str) -> None:
        self._by_key.pop(key, None)

    def clear(self) -> None:
        self._by_key.clear()
        self.errors.clear()

    # ----------------------------------------------------------------- read
    def get(self, key: str) -> type[BaseStrategy]:
        try:
            return self._by_key[key]
        except KeyError:
            raise UnknownStrategyError(key, self.keys()) from None

    def find(self, key: str) -> Optional[type[BaseStrategy]]:
        return self._by_key.get(key)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_key))

    def all(self) -> tuple[type[BaseStrategy], ...]:
        return tuple(self._by_key[k] for k in self.keys())

    def offerable(self) -> tuple[type[BaseStrategy], ...]:
        """Strategies the bot builder may offer as live options.

        Stable, not deprecated, and constructible from a key plus a symbol.
        Everything else stays installed and fully backtestable — being able to
        study a strategy before it is offered to anyone is the point of having
        a plugin system rather than a hardcoded list.
        """
        return tuple(c for c in self.all() if c.meta.offerable)

    def build(self, key: str, symbol: str, **params: Any) -> BaseStrategy:
        """Construct a strategy. Validation happens in ``BaseStrategy.__init__``."""
        return self.get(key)(symbol=symbol, **params)

    def describe(self) -> list[dict[str, Any]]:
        return [c.describe() for c in self.all()]

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self) -> Iterator[type[BaseStrategy]]:
        return iter(self.all())


def _with_source(meta, source: str):
    from dataclasses import replace
    return replace(meta, source=source)


_DEFAULT = StrategyRegistry()


def default_registry() -> StrategyRegistry:
    """The shared registry. Callers that just want "installed strategies"."""
    return _DEFAULT


__all__ = ["StrategyRegistry", "StrategyRegistryError", "DuplicateStrategyError",
           "InvalidStrategyError", "UnknownStrategyError", "default_registry"]
