"""What a strategy declares about itself.

A strategy plugin has to answer questions no signal-generating method can:
what is it called, who wrote it, which version is this, what can be tuned and
between which bounds, and what does it do. Today those answers live in the
places that consume them — a label in a registry dict, a parameter default in a
constructor signature, a tuning range in whichever optimiser happens to sweep
it. Declaring them on the class means a new strategy carries its own answers,
and installing one is dropping in a file rather than editing five.

Two decisions here are load-bearing.

**Parameters are declared, not inferred from the constructor signature.** A
signature gives a name and a default and nothing else — no bounds, no units, no
tuning range, no description. Inferring from it produces an optimiser that
cheerfully tries an EMA period of -3, and a UI that renders every knob as a bare
text box.

**A version is required and must be a real version.** Strategy results are only
comparable within a version: change the entry rule and last month's backtest
describes a different strategy under the same name. An unversioned plugin makes
that indistinguishable from noise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

#: Semantic version, major.minor.patch. Deliberately strict: "v2", "2.1" and
#: "latest" all sort unpredictably, and a version that cannot be compared cannot
#: answer "is this the same strategy that produced that backtest?".
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class ParamType(str, Enum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    CHOICE = "choice"


class Maturity(str, Enum):
    """How much the platform trusts this strategy.

    Not decoration: ``EXPERIMENTAL`` keeps a strategy out of the live builder
    while leaving it fully available to backtests, which is what lets a plugin
    be installed and studied before it is offered to anyone as a bot.
    """

    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class Parameter:
    """One tunable knob, fully described.

    ``optimise`` is separate from ``minimum``/``maximum`` on purpose. The bounds
    are what is *valid*; the optimisation values are what is *worth trying*. An
    EMA period is valid anywhere from 2 to 500 and worth sweeping over maybe six
    values — an optimiser that confuses the two searches 499 candidates and
    overfits every one of them.
    """

    name: str
    type: ParamType = ParamType.INT
    default: Any = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    choices: tuple[Any, ...] = ()
    description: str = ""
    #: "bars", "%", "×ATR" — rendered next to the value. A number whose unit is
    #: a guess is the 100×-risk bug waiting to happen again.
    unit: str = ""
    #: Explicit values to try when optimising. Empty means derive from the
    #: bounds and step.
    optimise: tuple[Any, ...] = ()
    #: Whether an optimiser may touch this at all. Off by default: sweeping
    #: every declared parameter is how a search space explodes.
    tunable: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a parameter needs a name")
        if self.type is ParamType.CHOICE and not self.choices:
            raise ValueError(f"parameter {self.name!r} is a choice with no choices")
        if (self.minimum is not None and self.maximum is not None
                and self.minimum > self.maximum):
            raise ValueError(
                f"parameter {self.name!r} has minimum {self.minimum} above "
                f"maximum {self.maximum}")

    # ---------------------------------------------------------------- values
    def coerce(self, value: Any) -> Any:
        """Convert to the declared type, or raise ``ValueError``.

        HTTP and JSON deliver "14" where an int is meant, and refusing a valid
        request over its wire format is not validation, it is friction. What is
        NOT accepted is a silent change of meaning: 14.7 for an int parameter
        raises rather than truncating to 14, because a bar count the user did
        not choose is a different strategy.
        """
        if self.type is ParamType.BOOL:
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("true", "1", "yes", "on"):
                return True
            if text in ("false", "0", "no", "off"):
                return False
            raise ValueError(f"{self.name}: {value!r} is not a boolean")
        if self.type is ParamType.INT:
            number = float(value)
            if number != int(number):
                raise ValueError(
                    f"{self.name}: {value!r} is not a whole number "
                    f"({self.unit or 'this parameter'} cannot be fractional)")
            return int(number)
        if self.type is ParamType.FLOAT:
            return float(value)
        if self.type is ParamType.CHOICE:
            if value not in self.choices:
                raise ValueError(
                    f"{self.name}: {value!r} is not one of "
                    f"{', '.join(map(str, self.choices))}")
            return value
        return str(value)

    def check(self, value: Any) -> Optional[str]:
        """Bounds check on an already-coerced value. ``None`` means it passes."""
        if self.type in (ParamType.BOOL, ParamType.STRING, ParamType.CHOICE):
            return None
        if self.minimum is not None and value < self.minimum:
            return (f"{self.name} is {value}{self._unit()}, below the minimum "
                    f"{self.minimum}{self._unit()}")
        if self.maximum is not None and value > self.maximum:
            return (f"{self.name} is {value}{self._unit()}, above the maximum "
                    f"{self.maximum}{self._unit()}")
        return None

    def _unit(self) -> str:
        return f" {self.unit}" if self.unit else ""

    def grid(self) -> tuple[Any, ...]:
        """Candidate values for an optimiser.

        Explicit ``optimise`` values win; then ``choices``; then a walk from
        ``minimum`` to ``maximum`` by ``step``. Returns empty when the parameter
        is not tunable or is unbounded — an unbounded sweep is not a sweep, and
        silently inventing a range for it is how an optimiser reports a best
        value from a space nobody chose.
        """
        if not self.tunable:
            return ()
        if self.optimise:
            return tuple(self.optimise)
        if self.choices:
            return tuple(self.choices)
        if self.minimum is None or self.maximum is None:
            return ()
        step = self.step or (1 if self.type is ParamType.INT else None)
        if not step or step <= 0:
            return ()
        out: list[Any] = []
        value = float(self.minimum)
        # <= with a tolerance: 0.1-steps accumulate error and would drop the
        # final candidate, so a range declared 1.0–2.0 would silently stop at 1.9.
        while value <= float(self.maximum) + 1e-9:
            out.append(int(round(value)) if self.type is ParamType.INT else round(value, 10))
            value += float(step)
        return tuple(dict.fromkeys(out))

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type.value, "default": self.default,
                "minimum": self.minimum, "maximum": self.maximum, "step": self.step,
                "choices": list(self.choices), "description": self.description,
                "unit": self.unit, "tunable": self.tunable,
                "optimise": list(self.grid())}


@dataclass(frozen=True)
class StrategyMeta:
    """Everything about a strategy that is not its signal logic."""

    key: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    maturity: Maturity = Maturity.EXPERIMENTAL
    tags: tuple[str, ...] = ()
    #: "crypto", "stocks", "forex". Empty means unrestricted, which is a claim
    #: worth making deliberately rather than by omission.
    asset_classes: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()
    #: Market regimes this strategy expects to work in. Empty = any.
    regimes: tuple[str, ...] = ()
    #: Constructor arguments with no default that a caller MUST supply. A
    #: strategy with any of these cannot be built from a key and a symbol alone,
    #: so the bot builder does not offer it — listing something the builder
    #: would crash on is worse than not listing it.
    requires: tuple[str, ...] = ()
    changelog: tuple[str, ...] = ()
    doc_url: str = ""
    #: Set by the loader, not the author: where this plugin came from.
    source: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("a strategy needs a key")
        if not _SEMVER.match(self.version):
            raise ValueError(
                f"strategy {self.key!r} has version {self.version!r} — "
                "major.minor.patch is required, because results are only "
                "comparable within a version")

    @property
    def offerable(self) -> bool:
        """Whether the bot builder may offer this as a live strategy.

        Stable, not deprecated, and constructible from a key plus a symbol.
        Everything else stays installed and backtestable — the distinction is
        what a plugin system is for.
        """
        return self.maturity is Maturity.STABLE and not self.requires

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "version": self.version,
                "description": self.description, "author": self.author,
                "maturity": self.maturity.value, "tags": list(self.tags),
                "asset_classes": list(self.asset_classes),
                "timeframes": list(self.timeframes), "regimes": list(self.regimes),
                "requires": list(self.requires), "changelog": list(self.changelog),
                "doc_url": self.doc_url, "source": self.source,
                "offerable": self.offerable}


@dataclass(frozen=True)
class ValidationIssue:
    parameter: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of checking a parameter set.

    Reports EVERY problem, not the first. Being told "fast must be below slow",
    fixing it, and then being told the period is out of range is a worse
    experience than being told both at once — the same reason the risk engine
    reports every violated rule.
    """

    ok: bool
    values: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def messages(self) -> tuple[str, ...]:
        return tuple(i.message for i in self.issues)

    def explain(self) -> str:
        return "; ".join(self.messages) if self.issues else "valid"

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "values": dict(self.values),
                "issues": [{"parameter": i.parameter, "message": i.message}
                           for i in self.issues]}


def validate(parameters: Sequence[Parameter],
             supplied: Mapping[str, Any]) -> ValidationResult:
    """Coerce and bounds-check ``supplied`` against declared ``parameters``.

    Undeclared keys pass through untouched. That is deliberate and it is the
    compatibility seam: existing call sites hand strategies keyword arguments
    that predate any declaration, and rejecting them would break working bots
    to enforce a convention introduced afterwards. A strategy that wants them
    checked declares them.
    """
    issues: list[ValidationIssue] = []
    values: dict[str, Any] = dict(supplied)
    for param in parameters:
        if param.name not in supplied:
            if param.default is not None:
                values[param.name] = param.default
            continue
        try:
            coerced = param.coerce(supplied[param.name])
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(param.name, str(exc)))
            continue
        problem = param.check(coerced)
        if problem:
            issues.append(ValidationIssue(param.name, problem))
        else:
            values[param.name] = coerced
    return ValidationResult(ok=not issues, values=values, issues=tuple(issues))


__all__ = ["ParamType", "Maturity", "Parameter", "StrategyMeta",
           "ValidationIssue", "ValidationResult", "validate"]
