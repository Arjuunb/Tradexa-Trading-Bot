"""Finding installed strategies.

Two ways in, because they answer different needs:

``discover_directory(path)``  — drop a ``.py`` file in the plugins folder. The
    zero-ceremony route: no packaging, no reinstall, no restart of anything but
    the process. This is what "install a strategy without modifying the trading
    engine" means for someone writing their own.

``discover_entry_points()``  — a pip-installable package declaring
    ``[project.entry-points."tradexa.strategies"]``. The distributable route:
    versioned, resolvable by dependency, and installable by name. This is what
    it means for someone SHARING one.

**One bad plugin must not take down the platform.** A file with a syntax error,
a missing import or a duplicate key is recorded on the registry's ``errors``
list and skipped. The alternative — an exception propagating out of discovery —
means one broken third-party file stops every strategy from loading, including
the ones running live bots. Failures are visible (they surface in the API and
in the boot log) rather than fatal.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable, Optional

from tradexa.strategy.base import BaseStrategy
from tradexa.strategy.registry import (
    StrategyRegistry, StrategyRegistryError, default_registry,
)

#: Entry-point group a distributable strategy package declares.
ENTRY_POINT_GROUP = "tradexa.strategies"

#: Files skipped in a plugins directory. Dunders and leading underscores are
#: private helpers a plugin author may want to share between strategies.
_SKIP_PREFIXES = ("_", ".")


def _target(registry: Optional[StrategyRegistry]) -> StrategyRegistry:
    """The registry to write into.

    Written as an explicit ``is None`` check because the obvious
    ``registry or default_registry()`` is a bug here: ``StrategyRegistry``
    defines ``__len__``, so an EMPTY registry is falsy — which is every
    registry on its first call, including every test's. Registration then
    landed in the shared default while the caller's stayed empty, and the
    caller saw the classes returned but none of them registered.
    """
    return default_registry() if registry is None else registry


def _record(registry: StrategyRegistry, source: str, exc: BaseException) -> None:
    registry.errors.append({
        "source": source,
        "error": type(exc).__name__,
        "message": str(exc),
        # The traceback's last frame is what makes a plugin author's syntax
        # error fixable from the API response rather than only from the log.
        "detail": traceback.format_exc(limit=3).strip().splitlines()[-1],
    })


def strategies_in(module: Any) -> tuple[type[BaseStrategy], ...]:
    """Concrete ``BaseStrategy`` subclasses DEFINED in ``module``.

    Defined, not merely present: a plugin that does ``from x import
    EMAStrategy`` to subclass it would otherwise re-register EMA from a second
    source and trip the duplicate-key guard on a file that did nothing wrong.
    """
    out = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (issubclass(obj, BaseStrategy) and obj is not BaseStrategy
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
                and getattr(obj, "meta", None) is not None
                and obj.meta.key != BaseStrategy.meta.key):
            out.append(obj)
    return tuple(out)


def register_module(module: Any, registry: Optional[StrategyRegistry] = None,
                    *, source: str = "") -> tuple[type[BaseStrategy], ...]:
    """Register every strategy a module defines. Conflicts are recorded, not raised."""
    registry = _target(registry)
    found = []
    for cls in strategies_in(module):
        try:
            registry.register(cls, source=source or module.__name__)
            found.append(cls)
        except StrategyRegistryError as exc:
            _record(registry, f"{source or module.__name__}:{cls.__qualname__}", exc)
    return tuple(found)


def discover_directory(path: str | Path,
                       registry: Optional[StrategyRegistry] = None,
                       *, package: str = "tradexa_plugins"
                       ) -> tuple[type[BaseStrategy], ...]:
    """Import every ``.py`` file in ``path`` and register what it defines.

    Modules are loaded under a synthetic package name so two plugin directories
    can each hold a ``momentum.py`` without the second silently resolving to the
    first through ``sys.modules``.

    A missing directory is not an error. The plugins folder is optional by
    design — a deployment that never installs a third-party strategy should not
    have to create an empty directory to boot.
    """
    registry = _target(registry)
    directory = Path(path)
    if not directory.is_dir():
        return ()

    found: list[type[BaseStrategy]] = []
    for file in sorted(directory.glob("*.py")):
        if file.name.startswith(_SKIP_PREFIXES):
            continue
        mod_name = f"{package}.{directory.name}.{file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, file)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {file}")
            module = importlib.util.module_from_spec(spec)
            # Registered BEFORE exec so a plugin that imports itself, or uses
            # dataclasses (which look the module up by name), resolves.
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
        except BaseException as exc:  # noqa: BLE001 — one bad plugin, not all of them
            sys.modules.pop(mod_name, None)
            _record(registry, str(file), exc)
            continue
        found.extend(register_module(module, registry, source=str(file)))
    return tuple(found)


def discover_package(package_name: str,
                     registry: Optional[StrategyRegistry] = None
                     ) -> tuple[type[BaseStrategy], ...]:
    """Import every submodule of an importable package and register them.

    Used for the built-in strategies, which live in a real package rather than
    a plugins folder. Same registration path as a third-party plugin — built-in
    is a location, not a privilege, and a bug in the plugin path would show up
    immediately rather than only for users.
    """
    registry = _target(registry)
    try:
        package = importlib.import_module(package_name)
    except BaseException as exc:  # noqa: BLE001
        _record(registry, package_name, exc)
        return ()

    found: list[type[BaseStrategy]] = []
    for info in pkgutil.iter_modules(getattr(package, "__path__", [])):
        if info.name.startswith(_SKIP_PREFIXES):
            continue
        full = f"{package_name}.{info.name}"
        try:
            module = importlib.import_module(full)
        except BaseException as exc:  # noqa: BLE001
            _record(registry, full, exc)
            continue
        found.extend(register_module(module, registry, source=full))
    return tuple(found)


def discover_entry_points(registry: Optional[StrategyRegistry] = None,
                          *, group: str = ENTRY_POINT_GROUP
                          ) -> tuple[type[BaseStrategy], ...]:
    """Register strategies from pip-installed packages.

    An entry point may point at a strategy class or at a module holding several;
    both are accepted, because forcing one shape would make the simplest useful
    plugin (a module with two related strategies) the awkward case.
    """
    registry = _target(registry)
    try:
        from importlib.metadata import entry_points
        # The 3.10+ selectable API. 3.9 and earlier return a plain dict, and
        # the fallback keeps this working there rather than raising on a
        # signature difference that has nothing to do with plugins.
        try:
            points = entry_points(group=group)
        except TypeError:  # pragma: no cover - Python < 3.10
            points = entry_points().get(group, [])
    except BaseException as exc:  # noqa: BLE001
        _record(registry, f"entry_points({group})", exc)
        return ()

    found: list[type[BaseStrategy]] = []
    for point in points:
        try:
            loaded = point.load()
        except BaseException as exc:  # noqa: BLE001
            _record(registry, f"{group}:{point.name}", exc)
            continue
        if inspect.isclass(loaded):
            try:
                registry.register(loaded, source=f"{group}:{point.name}")
                found.append(loaded)
            except StrategyRegistryError as exc:
                _record(registry, f"{group}:{point.name}", exc)
        else:
            found.extend(register_module(loaded, registry,
                                         source=f"{group}:{point.name}"))
    return tuple(found)


def discover_all(*, packages: Iterable[str] = (),
                 directories: Iterable[str | Path] = (),
                 entry_points: bool = True,
                 registry: Optional[StrategyRegistry] = None
                 ) -> StrategyRegistry:
    """Run every discovery source in order and return the registry.

    Order is deliberate: built-in packages first, then pip-installed plugins,
    then the local plugins directory. A local file cannot silently displace a
    built-in — it hits the duplicate-key guard and is reported — which means the
    strategy a saved bot config names cannot change under it because someone
    dropped a file in a folder.
    """
    registry = _target(registry)
    for name in packages:
        discover_package(name, registry)
    if entry_points:
        discover_entry_points(registry)
    for path in directories:
        discover_directory(path, registry)
    return registry


__all__ = ["ENTRY_POINT_GROUP", "strategies_in", "register_module",
           "discover_directory", "discover_package", "discover_entry_points",
           "discover_all"]
