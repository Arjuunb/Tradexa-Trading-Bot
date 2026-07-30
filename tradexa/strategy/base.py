"""``BaseStrategy`` — what every strategy plugin inherits.

It **subclasses the existing** ``bot.strategies.base.Strategy`` rather than
restating it. The bar-feeding contract (``on_bar`` appends and calls
``generate``) is tested, in production, and shared with the backtester; a
parallel implementation would agree the day it was written and diverge on the
first fix, and then a plugin would behave differently in a backtest from live.

What this adds is everything a plugin needs that signal logic cannot express:

    meta                 identity, version, maturity, asset classes
    parameters           declared knobs with types, bounds, units, descriptions
    validate_params()    coercion and bounds, reporting every problem at once
    validate()           cross-parameter rules the author writes
    optimisation_grid()  what an optimiser may sweep, and over what
    docs()               reference text generated from the class itself

The effect on the engine is the point: a new strategy is a file that declares
these, and installing one means putting the file somewhere. Nothing in the
trading engine is edited to add, remove or version a strategy.

**Backwards compatibility is deliberate and load-bearing.** Undeclared keyword
arguments pass through untouched. Existing strategies were written before any of
this existed and their call sites hand them arguments that no ``Parameter``
describes; rejecting those would break working bots to enforce a convention
introduced afterwards. Declaring a parameter is what opts it into validation.
"""
from __future__ import annotations

import inspect
from typing import Any, Iterable, Mapping, Optional, Sequence

from bot.strategies.base import Strategy

from tradexa.strategy.metadata import (
    Maturity, Parameter, StrategyMeta, ValidationResult, validate,
)


class StrategyParameterError(ValueError):
    """Raised when a strategy is constructed with parameters it declared invalid.

    A ``ValueError`` subclass so existing ``except ValueError`` handlers around
    strategy construction keep working — several call sites already catch that
    from constructors like ``EMAStrategy``'s "fast must be < slow".
    """

    def __init__(self, key: str, result: ValidationResult) -> None:
        self.key, self.result = key, result
        super().__init__(f"{key}: {result.explain()}")


class BaseStrategy(Strategy):
    """The contract every installable strategy satisfies."""

    #: Overridden by every concrete strategy. The default exists so an
    #: incomplete plugin fails a clear check rather than an AttributeError deep
    #: inside a UI template.
    meta: StrategyMeta = StrategyMeta(key="base", name="Base Strategy",
                                      maturity=Maturity.EXPERIMENTAL)
    parameters: tuple[Parameter, ...] = ()

    def __init__(self, symbol: str, **params: Any) -> None:
        result = self.validate_params(params)
        if not result.ok:
            raise StrategyParameterError(self.meta.key, result)
        super().__init__(symbol, **dict(result.values))
        # `name` predates `meta` and is read by the backtester, the reporting
        # layer and the bot manager. Kept in step rather than replaced: two
        # names for one strategy is how a trade log stops matching a config.
        if type(self).name in ("base", "", None):
            type(self).name = self.meta.key

    # ─────────────────────────────────────────────────────── declarations
    @classmethod
    def parameter(cls, name: str) -> Optional[Parameter]:
        for p in cls.parameters:
            if p.name == name:
                return p
        return None

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        """Declared defaults, and only those.

        Constructor defaults are NOT merged in. They are unreachable without
        calling the constructor, and a "default" that a caller cannot see before
        instantiating is not a default a UI can render or an optimiser can start
        from. ``undeclared_parameters()`` reports the gap instead of papering
        over it.
        """
        return {p.name: p.default for p in cls.parameters if p.default is not None}

    @classmethod
    def undeclared_parameters(cls) -> tuple[str, ...]:
        """Constructor arguments with no ``Parameter`` declaration.

        Not an error — a strategy may take a collaborator object that is not a
        tunable knob — but it IS the list of things no UI can render and no
        optimiser can sweep. Reported so the gap is visible rather than a
        mystery about why a knob never appears.
        """
        declared = {p.name for p in cls.parameters}
        try:
            sig = inspect.signature(cls.__init__)
        except (TypeError, ValueError):  # pragma: no cover - builtins only
            return ()
        return tuple(
            name for name, p in sig.parameters.items()
            if name not in ("self", "symbol") and name not in declared
            and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL))

    # ─────────────────────────────────────────────────────── validation
    @classmethod
    def validate_params(cls, params: Mapping[str, Any]) -> ValidationResult:
        """Coerce and check ``params``, then apply the strategy's own rules.

        Two layers because they answer different questions. The declarative one
        knows a period must be a positive integer; only the author knows that
        the fast one must be below the slow one. Both run, and both report, so a
        caller is told everything wrong at once rather than one item per attempt.
        """
        result = validate(cls.parameters, params)
        extra = cls.validate(dict(result.values))
        if not extra:
            return result
        from tradexa.strategy.metadata import ValidationIssue
        issues = result.issues + tuple(
            i if isinstance(i, ValidationIssue) else ValidationIssue("", str(i))
            for i in extra)
        return ValidationResult(ok=False, values=result.values, issues=issues)

    @classmethod
    def validate(cls, params: Mapping[str, Any]) -> Sequence[Any]:
        """Cross-parameter rules. Override; return messages, or nothing.

        Receives values already coerced and bounds-checked, so an implementation
        compares numbers rather than re-parsing strings.
        """
        return ()

    # ─────────────────────────────────────────────────────── optimisation
    @classmethod
    def optimisation_grid(cls, only: Optional[Iterable[str]] = None
                          ) -> dict[str, tuple[Any, ...]]:
        """Values an optimiser may try, per tunable parameter.

        Only parameters explicitly marked ``tunable`` appear. Sweeping every
        declared knob is how a search space explodes and how an optimiser
        reports a "best" configuration selected from thousands of candidates on
        one sample of history — which is overfitting with a progress bar.
        """
        wanted = set(only) if only is not None else None
        out: dict[str, tuple[Any, ...]] = {}
        for p in cls.parameters:
            if wanted is not None and p.name not in wanted:
                continue
            values = p.grid()
            if values:
                out[p.name] = values
        return out

    @classmethod
    def optimisation_size(cls, only: Optional[Iterable[str]] = None) -> int:
        """How many combinations a full sweep would evaluate.

        Exposed so a caller can refuse before starting rather than discover it
        by waiting. A grid that multiplies out to five figures is a decision,
        and it should be one someone makes on purpose.
        """
        size = 1
        for values in cls.optimisation_grid(only).values():
            size *= len(values)
        return size if cls.optimisation_grid(only) else 0

    # ─────────────────────────────────────────────────────── documentation
    @classmethod
    def own_docstring(cls) -> str:
        """This class's docstring, never an inherited one.

        ``inspect.getdoc`` walks the MRO, so a strategy that declares no
        docstring silently documented itself with ``BaseStrategy``'s — every
        such plugin's reference page read "The contract every installable
        strategy satisfies", which is true of the base class and describes
        nothing about the strategy. Absent is the honest answer; the metadata
        description carries the summary.
        """
        doc = cls.__dict__.get("__doc__")
        return inspect.cleandoc(doc) if doc else ""

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Everything about this strategy, as data. What the API returns."""
        return {
            **cls.meta.as_dict(),
            "class": f"{cls.__module__}.{cls.__qualname__}",
            "parameters": [p.as_dict() for p in cls.parameters],
            "defaults": cls.defaults(),
            "optimisation": {k: list(v) for k, v in cls.optimisation_grid().items()},
            "optimisation_size": cls.optimisation_size(),
            "undeclared_parameters": list(cls.undeclared_parameters()),
            "docstring": cls.own_docstring(),
        }

    @classmethod
    def docs(cls) -> str:
        """Reference documentation, generated from the class.

        Generated rather than hand-written so it cannot drift: a parameter that
        is renamed is renamed here, and a strategy whose docs are missing is a
        strategy whose docstring is missing, which is visible in review.
        """
        m = cls.meta
        lines = [f"# {m.name}", ""]
        lines.append(f"`{m.key}` · v{m.version} · {m.maturity.value}"
                     + (f" · {m.author}" if m.author else ""))
        lines.append("")
        if m.description:
            lines += [m.description, ""]
        doc = cls.own_docstring()
        if doc:
            lines += [doc, ""]
        for label, values in (("Asset classes", m.asset_classes),
                              ("Timeframes", m.timeframes),
                              ("Regimes", m.regimes),
                              ("Tags", m.tags)):
            if values:
                lines.append(f"**{label}:** {', '.join(values)}  ")
        if m.requires:
            lines.append(f"**Requires:** {', '.join(m.requires)} "
                         "(cannot be built from a symbol alone)  ")
        lines.append("")
        if cls.parameters:
            lines += ["## Parameters", "",
                      "| Name | Type | Default | Range | Tunable | Description |",
                      "|---|---|---|---|---|---|"]
            for p in cls.parameters:
                rng = "—"
                if p.choices:
                    rng = ", ".join(str(c) for c in p.choices)
                elif p.minimum is not None or p.maximum is not None:
                    rng = f"{p.minimum if p.minimum is not None else '−∞'}–" \
                          f"{p.maximum if p.maximum is not None else '∞'}"
                unit = f" {p.unit}" if p.unit else ""
                lines.append(
                    f"| `{p.name}` | {p.type.value} | {p.default}{unit} | {rng} | "
                    f"{'yes' if p.tunable else 'no'} | {p.description} |")
            lines.append("")
        grid = cls.optimisation_grid()
        if grid:
            lines += ["## Optimisation", "",
                      f"{cls.optimisation_size()} combinations across "
                      f"{len(grid)} parameter(s):", ""]
            for name, values in grid.items():
                lines.append(f"- `{name}`: {', '.join(str(v) for v in values)}")
            lines.append("")
        if m.changelog:
            lines += ["## Changelog", ""] + [f"- {c}" for c in m.changelog] + [""]
        return "\n".join(lines).rstrip() + "\n"


__all__ = ["BaseStrategy", "StrategyParameterError"]
