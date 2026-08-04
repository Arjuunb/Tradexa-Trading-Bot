"""Strategies as installable plugins.

What is being proven, in order of how much it would cost to get wrong:

1. A strategy can be installed WITHOUT editing the trading engine — the claim
   the whole phase exists to make true.
2. The declarations work: metadata, versioning, parameters, validation,
   optimisation and documentation each do something, rather than being fields
   nothing reads.
3. A broken or hostile plugin cannot take the platform down, silently displace a
   built-in, or install itself under another strategy's key.
"""
from __future__ import annotations

import textwrap
from typing import Optional

import pytest

from bot.types import Bar, Signal, SignalType
from tradexa.strategy import (
    BaseStrategy, DuplicateStrategyError, InvalidStrategyError, Maturity,
    ParamType, Parameter, StrategyMeta, StrategyParameterError,
    StrategyRegistry, UnknownStrategyError, discover_directory, register_module,
    strategies_in,
)


class Sample(BaseStrategy):
    """A sample strategy. This docstring is the generated documentation."""

    meta = StrategyMeta(key="sample", name="Sample", version="2.1.0",
                        description="Buys every bar above the lookback high.",
                        author="tests", maturity=Maturity.STABLE,
                        asset_classes=("crypto",), timeframes=("1h",),
                        tags=("test",), changelog=("2.1.0 — the one under test",))
    parameters = (
        Parameter("lookback", ParamType.INT, default=20, minimum=2, maximum=100,
                  unit="bars", tunable=True, optimise=(10, 20, 50),
                  description="Breakout window."),
        Parameter("threshold", ParamType.FLOAT, default=1.0, minimum=0.0,
                  maximum=5.0, step=0.5, tunable=True),
        Parameter("mode", ParamType.CHOICE, default="fast",
                  choices=("fast", "slow")),
        Parameter("enabled", ParamType.BOOL, default=True),
    )

    def __init__(self, symbol: str, *, lookback: int = 20, threshold: float = 1.0,
                 **params):
        super().__init__(symbol, lookback=lookback, threshold=threshold, **params)

    @classmethod
    def validate(cls, params):
        if params.get("mode") == "slow" and params.get("lookback", 0) < 10:
            return ("slow mode needs a lookback of at least 10 bars",)
        return ()

    def generate(self, bar: Bar) -> Optional[Signal]:
        return None


@pytest.fixture()
def registry():
    return StrategyRegistry()


# ═══════════════════════════════════════════ installing without engine edits

def test_a_plugin_file_installs_itself(tmp_path, registry):
    """The headline claim. A file appears in a directory; the strategy is
    installed. No import added anywhere, no registry dictionary edited, no
    engine module touched."""
    (tmp_path / "mine.py").write_text(textwrap.dedent('''
        from typing import Optional
        from bot.types import Bar, Signal
        from tradexa.strategy import BaseStrategy, Maturity, StrategyMeta

        class Mine(BaseStrategy):
            """My own strategy."""
            meta = StrategyMeta(key="mine", name="Mine", version="0.1.0",
                                maturity=Maturity.STABLE)
            def generate(self, bar: Bar) -> Optional[Signal]:
                return None
    '''))
    found = discover_directory(tmp_path, registry)
    assert [c.meta.key for c in found] == ["mine"]
    assert "mine" in registry
    assert registry.build("mine", "BTCUSDT").symbol == "BTCUSDT"


def test_the_loader_records_where_a_plugin_came_from(tmp_path, registry):
    """Provenance is stamped by the loader, never taken from the author — a
    plugin that could name its own origin could claim to be a built-in."""
    (tmp_path / "p.py").write_text(textwrap.dedent('''
        from tradexa.strategy import BaseStrategy, StrategyMeta
        class P(BaseStrategy):
            meta = StrategyMeta(key="p", name="P", source="built-in, honest")
            def generate(self, bar): return None
    '''))
    discover_directory(tmp_path, registry)
    assert str(tmp_path) in registry.get("p").meta.source
    assert "honest" not in registry.get("p").meta.source


def test_two_plugin_directories_can_hold_the_same_filename(tmp_path, registry):
    """Loaded under distinct synthetic module names. Otherwise the second
    ``momentum.py`` silently resolves to the first through ``sys.modules`` and a
    user's strategy runs someone else's code."""
    for name, key in (("a", "one"), ("b", "two")):
        d = tmp_path / name
        d.mkdir()
        (d / "momentum.py").write_text(textwrap.dedent(f'''
            from tradexa.strategy import BaseStrategy, StrategyMeta
            class M(BaseStrategy):
                meta = StrategyMeta(key="{key}", name="{key}")
                def generate(self, bar): return None
        '''))
        discover_directory(d, registry)
    assert set(registry.keys()) == {"one", "two"}


def test_a_missing_plugins_directory_is_not_an_error(tmp_path, registry):
    """A deployment that never installs a third-party strategy should not have
    to create an empty folder to boot."""
    assert discover_directory(tmp_path / "nope", registry) == ()
    assert registry.errors == []


# ═══════════════════════════════════════════ one bad plugin, not all of them

def test_a_plugin_with_a_syntax_error_does_not_stop_the_others(tmp_path, registry):
    """The failure mode that matters: a third-party file must not stop the
    strategies running live bots from loading."""
    (tmp_path / "broken.py").write_text("def oops(:\n")
    (tmp_path / "good.py").write_text(textwrap.dedent('''
        from tradexa.strategy import BaseStrategy, StrategyMeta
        class Good(BaseStrategy):
            meta = StrategyMeta(key="good", name="Good")
            def generate(self, bar): return None
    '''))
    discover_directory(tmp_path, registry)
    assert "good" in registry
    assert any("broken.py" in e["source"] for e in registry.errors)


def test_a_failure_is_recorded_with_something_actionable(tmp_path, registry):
    """Recorded, not swallowed. The author's only other clue would be a strategy
    that never appears, with nothing saying why."""
    (tmp_path / "bad.py").write_text("import a_module_that_does_not_exist\n")
    discover_directory(tmp_path, registry)
    assert len(registry.errors) == 1
    err = registry.errors[0]
    assert err["error"] == "ModuleNotFoundError"
    assert "a_module_that_does_not_exist" in err["message"]
    assert err["detail"]


def test_a_plugin_that_raises_on_import_is_contained(tmp_path, registry):
    (tmp_path / "angry.py").write_text("raise SystemExit('go away')\n")
    discover_directory(tmp_path, registry)
    assert registry.errors, "a SystemExit at import time escaped discovery"


def test_underscore_files_are_left_alone(tmp_path, registry):
    """A plugin author's shared helper is not a plugin."""
    (tmp_path / "_helpers.py").write_text("raise RuntimeError('should not import')\n")
    discover_directory(tmp_path, registry)
    assert registry.errors == []


# ═══════════════════════════════════════════ keys, conflicts and identity

def test_two_strategies_cannot_claim_one_key(registry):
    """Keys are how a saved bot configuration finds its code. Last-import-wins
    would quietly change what a running bot executes."""
    class Other(BaseStrategy):
        meta = StrategyMeta(key="sample", name="Impostor")

        def generate(self, bar):
            return None

    registry.register(Sample)
    with pytest.raises(DuplicateStrategyError) as exc:
        registry.register(Other)
    assert "sample" in str(exc.value)
    assert registry.get("sample") is Sample


def test_registering_the_same_class_twice_is_not_a_conflict(registry):
    """Re-importing a module is not two plugins fighting over a key."""
    registry.register(Sample)
    assert registry.register(Sample) is Sample


def test_a_local_plugin_cannot_displace_a_builtin(tmp_path, registry):
    """Discovery order is built-ins first. A file dropped in a folder must not
    change which code a saved bot config resolves to."""
    registry.register(Sample, source="builtin")
    (tmp_path / "impostor.py").write_text(textwrap.dedent('''
        from tradexa.strategy import BaseStrategy, StrategyMeta
        class Impostor(BaseStrategy):
            meta = StrategyMeta(key="sample", name="Impostor")
            def generate(self, bar): return None
    '''))
    discover_directory(tmp_path, registry)
    assert registry.get("sample") is Sample
    assert any("sample" in e["message"] for e in registry.errors)


def test_a_class_that_is_not_a_strategy_is_refused(registry):
    with pytest.raises(InvalidStrategyError):
        registry.register(dict)


def test_a_strategy_with_no_key_is_refused(registry):
    class NoKey(BaseStrategy):
        meta = StrategyMeta(key="", name="x") if False else None

        def generate(self, bar):
            return None

    with pytest.raises(InvalidStrategyError):
        registry.register(NoKey)


def test_a_strategy_that_never_declared_its_own_meta_is_refused(registry):
    """Inheriting the base placeholder is the most likely incomplete plugin, and
    it would otherwise register under the key "base"."""
    class Forgot(BaseStrategy):
        def generate(self, bar):
            return None

    with pytest.raises(InvalidStrategyError) as exc:
        registry.register(Forgot)
    assert "placeholder" in str(exc.value)


def test_an_abstract_strategy_is_refused(registry):
    """Rejected at registration with a reason, rather than at 3am when a bot
    tries to trade with it."""
    class Abstract(BaseStrategy):
        meta = StrategyMeta(key="abstract", name="Abstract")

    with pytest.raises(InvalidStrategyError) as exc:
        registry.register(Abstract)
    assert "generate" in str(exc.value)


def test_an_unknown_key_names_what_is_installed(registry):
    registry.register(Sample)
    with pytest.raises(UnknownStrategyError) as exc:
        registry.get("nope")
    assert "sample" in str(exc.value)


def test_an_empty_registry_is_not_silently_replaced(registry):
    """``StrategyRegistry`` defines ``__len__``, so an empty one is falsy, and
    ``registry or default_registry()`` — the obvious phrasing — discarded the
    caller's registry on its very first call. Registration landed in the shared
    default while the caller's stayed empty. Pinned because the symptom (classes
    returned, nothing registered) points nowhere near the cause."""
    import types
    from tradexa.strategy import default_registry
    module = types.ModuleType("fake_plugin_module")
    module.Sample = Sample
    Sample.__module__ = "fake_plugin_module"
    try:
        assert len(registry) == 0 and not registry
        register_module(module, registry)
        assert "sample" in registry
        assert "sample" not in default_registry()
    finally:
        Sample.__module__ = __name__


# ═══════════════════════════════════════════ metadata and versioning

def test_a_version_must_be_a_real_version():
    """Results are only comparable within a version. "v2" and "latest" do not
    sort, so they cannot answer "is this the strategy that produced that
    backtest?"."""
    for bad in ("v2", "2.1", "latest", "1.0.0-beta", ""):
        with pytest.raises(ValueError):
            StrategyMeta(key="x", name="X", version=bad)


def test_metadata_survives_the_round_trip():
    d = Sample.meta.as_dict()
    assert d["version"] == "2.1.0"
    assert d["maturity"] == "stable"
    assert d["asset_classes"] == ["crypto"]
    assert d["offerable"] is True


def test_maturity_decides_what_the_builder_may_offer(registry):
    """Not decoration: it is what lets a plugin be installed and studied before
    it is offered to anyone as a live bot."""
    class Experimental(BaseStrategy):
        meta = StrategyMeta(key="exp", name="Exp", maturity=Maturity.EXPERIMENTAL)

        def generate(self, bar):
            return None

    registry.register(Sample)
    registry.register(Experimental)
    assert [c.meta.key for c in registry.offerable()] == ["sample"]
    assert "exp" in registry, "an experimental plugin is still INSTALLED"


def test_a_strategy_needing_constructor_arguments_is_not_offered(registry):
    """It cannot be built from a key and a symbol, so offering it would put an
    option in the builder that crashes when chosen."""
    class NeedsSpec(BaseStrategy):
        meta = StrategyMeta(key="needs", name="Needs", maturity=Maturity.STABLE,
                            requires=("spec",))

        def generate(self, bar):
            return None

    registry.register(NeedsSpec)
    assert registry.offerable() == ()


def test_a_deprecated_strategy_stays_installed_but_unoffered(registry):
    """Existing bots keep running; new ones cannot be pointed at it."""
    class Old(BaseStrategy):
        meta = StrategyMeta(key="old", name="Old", maturity=Maturity.DEPRECATED)

        def generate(self, bar):
            return None

    registry.register(Old)
    assert "old" in registry and registry.offerable() == ()


# ═══════════════════════════════════════════ parameters and validation

def test_defaults_come_from_the_declarations():
    assert Sample.defaults() == {"lookback": 20, "threshold": 1.0,
                                 "mode": "fast", "enabled": True}


def test_a_string_from_a_form_is_coerced():
    """HTTP and JSON deliver "25" where an int is meant. Refusing a valid
    request over its wire format is friction, not validation."""
    result = Sample.validate_params({"lookback": "25"})
    assert result.ok and result.values["lookback"] == 25


def test_a_fractional_value_for_an_int_is_refused_not_truncated():
    """Truncating 14.7 to 14 silently runs a different strategy from the one
    that was asked for."""
    result = Sample.validate_params({"lookback": 14.7})
    assert not result.ok
    assert "whole number" in result.explain()


def test_bounds_are_enforced_with_units_in_the_message():
    result = Sample.validate_params({"lookback": 500})
    assert not result.ok
    assert "bars" in result.explain(), "the unit is what makes the limit readable"


def test_a_choice_outside_the_choices_is_refused():
    assert not Sample.validate_params({"mode": "sideways"}).ok


def test_booleans_accept_what_a_form_actually_sends():
    for value, expected in (("true", True), ("0", False), ("on", True),
                            ("no", False), (True, True)):
        assert Sample.validate_params({"enabled": value}).values["enabled"] is expected


def test_every_problem_is_reported_not_just_the_first():
    """Being refused, fixing one thing and being refused again is worse than
    being told both at once."""
    result = Sample.validate_params({"lookback": 500, "mode": "nope"})
    assert len(result.issues) == 2


def test_declarative_and_authored_rules_both_run():
    result = Sample.validate_params({"mode": "slow", "lookback": 3})
    assert not result.ok
    assert "at least 10" in result.explain()


def test_an_undeclared_parameter_passes_through():
    """The compatibility seam. Existing call sites hand strategies arguments
    that predate any declaration; rejecting them would break working bots to
    enforce a convention introduced afterwards."""
    result = Sample.validate_params({"legacy_knob": "whatever"})
    assert result.ok and result.values["legacy_knob"] == "whatever"


def test_construction_refuses_invalid_parameters():
    with pytest.raises(StrategyParameterError) as exc:
        Sample("BTCUSDT", lookback=1)
    assert "lookback" in str(exc.value)


def test_the_construction_error_is_still_a_valueerror():
    """Call sites already catch ValueError from strategy constructors; a new
    exception type would slip past them as a 500."""
    with pytest.raises(ValueError):
        Sample("BTCUSDT", lookback=1)


def test_undeclared_constructor_arguments_are_reported():
    """Not an error, but it is the list of knobs no UI can render and no
    optimiser can sweep."""
    class Partial(BaseStrategy):
        meta = StrategyMeta(key="partial", name="Partial")
        parameters = (Parameter("declared", ParamType.INT, default=1),)

        def __init__(self, symbol, *, declared=1, hidden=2, **params):
            super().__init__(symbol, declared=declared, hidden=hidden, **params)

        def generate(self, bar):
            return None

    assert Partial.undeclared_parameters() == ("hidden",)


# ═══════════════════════════════════════════ optimisation

def test_only_tunable_parameters_are_swept():
    """Sweeping every declared knob is how a search space explodes and how an
    optimiser reports a "best" configuration chosen from thousands of candidates
    on one sample of history."""
    grid = Sample.optimisation_grid()
    assert set(grid) == {"lookback", "threshold"}
    assert "mode" not in grid


def test_explicit_optimisation_values_win_over_the_bounds():
    """Bounds say what is VALID; the optimise list says what is worth trying. An
    optimiser that confuses them searches 99 candidates and overfits each one."""
    assert Sample.optimisation_grid()["lookback"] == (10, 20, 50)


def test_a_range_with_a_step_is_walked_completely():
    """Floating-point accumulation silently drops the last candidate, so a range
    declared 0.0–5.0 would quietly stop at 4.5."""
    values = Sample.optimisation_grid()["threshold"]
    assert values[0] == 0.0 and values[-1] == 5.0


def test_an_unbounded_tunable_parameter_yields_no_grid():
    """Inventing a range for it would let an optimiser report a best value from
    a space nobody chose."""
    p = Parameter("free", ParamType.FLOAT, default=1.0, tunable=True)
    assert p.grid() == ()


def test_the_search_size_is_knowable_before_starting():
    """A grid that multiplies out to five figures should be a decision someone
    makes on purpose, not something they discover by waiting."""
    assert Sample.optimisation_size() == len((10, 20, 50)) * len(
        Sample.optimisation_grid()["threshold"])


def test_a_strategy_with_nothing_tunable_reports_zero():
    class Fixed(BaseStrategy):
        meta = StrategyMeta(key="fixed", name="Fixed")

        def generate(self, bar):
            return None

    assert Fixed.optimisation_size() == 0


# ═══════════════════════════════════════════ documentation

def test_documentation_is_generated_from_the_class():
    """Generated, so it cannot drift: a renamed parameter is renamed here."""
    doc = Sample.docs()
    assert "# Sample" in doc
    assert "v2.1.0" in doc
    assert "`lookback`" in doc and "Breakout window." in doc
    assert "bars" in doc
    assert "2.1.0 — the one under test" in doc


def test_documentation_does_not_borrow_the_base_classs_docstring():
    """``inspect.getdoc`` walks the MRO, so a strategy with no docstring
    documented itself with BaseStrategy's — every such plugin's reference page
    read "The contract every installable strategy satisfies"."""
    class Undocumented(BaseStrategy):
        meta = StrategyMeta(key="undoc", name="Undoc")

        def generate(self, bar):
            return None

    assert Undocumented.own_docstring() == ""
    assert "contract every installable" not in Undocumented.docs()


def test_describe_carries_everything_an_api_needs():
    d = Sample.describe()
    for field in ("key", "name", "version", "maturity", "parameters", "defaults",
                  "optimisation", "optimisation_size", "docstring", "class"):
        assert field in d, f"{field} missing from describe()"
    assert d["parameters"][0]["name"] == "lookback"


# ═══════════════════════════════════════════ module scanning

def test_only_classes_defined_in_the_module_are_registered():
    """A plugin that imports a strategy to subclass it would otherwise
    re-register the import from a second source and trip the duplicate guard on
    a file that did nothing wrong."""
    import types
    module = types.ModuleType("importer")
    module.Sample = Sample          # imported, not defined here
    assert strategies_in(module) == ()


def test_the_base_class_itself_is_never_registered():
    import types
    module = types.ModuleType("m")
    module.BaseStrategy = BaseStrategy
    assert strategies_in(module) == ()


# ═══════════════════════════════════════════ every strategy, no exceptions

def test_every_strategy_class_in_the_repo_inherits_basestrategy():
    """The brief's flat requirement, checked against the source rather than
    against memory.

    Walks every ``.py`` file for classes that subclass a Strategy base and
    asserts each one reaches ``BaseStrategy``. Written as an AST + import check
    because the gap it caught was invisible to every other test: the engine's
    own ``SupportResistanceRejection`` lived in ``bot/strategies/`` and inherited
    the old ``Strategy`` directly, so eight strategies were plugins and a ninth,
    in a different directory, quietly was not.
    """
    import ast
    import importlib
    import pathlib
    import sys

    root = pathlib.Path(__file__).resolve().parents[1]
    # The backend tree is not on the path in a root-suite run (only the reverse
    # is wired, by automation-hub/conftest.py). Added here rather than skipping
    # that half: a check that silently covers one of the two directories holding
    # strategies would have missed the exact gap this test exists to catch.
    hub = str(root / "automation-hub")
    if hub not in sys.path:
        sys.path.append(hub)
    # Directories holding strategy implementations, with their import prefix.
    areas = {root / "bot" / "strategies": "bot.strategies",
             root / "automation-hub" / "strategies": "strategies"}

    checked = []
    for directory, prefix in areas.items():
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_") or path.name == "base.py":
                continue
            tree = ast.parse(path.read_text())
            names = [n.name for n in ast.walk(tree)
                     if isinstance(n, ast.ClassDef)
                     and any(_base_name(b).endswith("Strategy")
                             or _base_name(b) in ("HubStrategy", "ConfirmationEnsemble")
                             for b in n.bases)]
            if not names:
                continue
            module = importlib.import_module(f"{prefix}.{path.stem}")
            for name in names:
                cls = getattr(module, name, None)
                if cls is None or not isinstance(cls, type):
                    continue
                assert issubclass(cls, BaseStrategy), (
                    f"{path.name}:{name} does not inherit BaseStrategy — it is a "
                    "strategy the plugin system cannot describe, validate, "
                    "optimise or document")
                checked.append(name)

    assert len(checked) >= 9, f"only checked {checked} — the walk found too few"


def _base_name(node) -> str:
    """The textual name of a class base, for either ``X`` or ``mod.X``."""
    import ast
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def test_the_engines_own_strategy_is_a_plugin():
    """Pinned specifically. It is reachable from the CLI, the config loader and
    api/index.py, none of which go through the hub's registry — so nothing else
    here would notice it regressing to a plain Strategy."""
    from bot.strategies import SupportResistanceRejection as S
    assert issubclass(S, BaseStrategy)
    assert S.meta.key == "sr_rejection"
    assert S.meta.version and S.parameters
    assert S.optimisation_grid(), "no tunable parameters declared"


def test_the_lazy_reexport_survives_every_import_order():
    """``bot/strategies/__init__`` re-exports lazily to break a cycle:
    tradexa.strategy imports bot.strategies.base, and the strategy imports
    tradexa.strategy. Whichever side is imported first must work, and the
    failure mode is an ImportError at startup — which no other test would reach,
    because by then the modules are already in sys.modules."""
    import subprocess
    import sys

    orders = [
        "import tradexa.strategy; from bot.strategies import SupportResistanceRejection",
        "from bot.strategies import SupportResistanceRejection; import tradexa.strategy",
        "import bot.strategies.support_resistance",
        "import bot.config",
        "from bot.strategies import Strategy",
    ]
    for probe in orders:
        proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                              text=True, cwd=str(__import__("pathlib").Path(
                                  __file__).resolve().parents[1]))
        assert proc.returncode == 0, f"import order failed: {probe}\n{proc.stderr}"


def test_a_config_can_name_an_installed_plugin_without_editing_the_loader():
    """``bot/config.py`` held the second hand-maintained strategy map in the
    codebase. A YAML config naming a plugin must resolve without that dict being
    edited — otherwise "install without modifying the trading engine" is true of
    the hub and false of the CLI."""
    from bot.config import _resolve_strategy
    from tradexa.strategy import default_registry

    registry = default_registry()
    try:
        registry.register(Sample)
        assert _resolve_strategy("sample") is Sample
    finally:
        registry.unregister("sample")


def test_a_historical_config_name_still_wins_over_a_plugin_key():
    """An installed plugin must not capture a name an existing config already
    resolves to — that would silently change what a saved configuration runs."""
    from bot.config import _STRATEGY_ALIASES, _resolve_strategy
    from tradexa.strategy import default_registry

    class Impostor(BaseStrategy):
        meta = StrategyMeta(key="support_resistance_rejection", name="Impostor")

        def generate(self, bar):
            return None

    registry = default_registry()
    try:
        registry.register(Impostor, replace=True)
        assert (_resolve_strategy("support_resistance_rejection")
                is _STRATEGY_ALIASES["support_resistance_rejection"])
    finally:
        registry.unregister("support_resistance_rejection")
