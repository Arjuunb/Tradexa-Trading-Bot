"""The bot catalog, now built from discovery instead of by hand.

``tests/test_strategy_plugins.py`` proves the plugin machinery works. This file
proves the swap was safe: that the catalog the UI and the BotManager read is
exactly what it was, that every existing strategy came through the migration
intact, and that a file dropped in the plugins directory really does reach the
builder without anyone editing the engine.
"""
from __future__ import annotations

import textwrap

import pytest

from bots import registry as reg
from tradexa.strategy import BaseStrategy, Maturity


@pytest.fixture(autouse=True)
def _restore_registry():
    """Each test gets the real discovery, and leaves it as it found it."""
    yield
    reg.PLUGINS_DIR = reg.Path(reg.os.environ.get(
        "HUB_PLUGINS_DIR", str(reg.Path(reg.__file__).resolve().parents[1] / "plugins")))
    reg.STRATEGIES.refresh()


# ── the catalog is unchanged ────────────────────────────────────────────────

def test_the_offered_strategies_are_exactly_what_they_were():
    """The migration's safety property. This dictionary drives the bot builder;
    a strategy silently appearing or vanishing from it is a product change, and
    this phase was supposed to be a refactor.

    Adding a strategy to this list is a one-word change in the plugin's own
    file — raising its maturity — and that change should fail this test, which
    is what makes it deliberate.
    """
    assert set(reg.STRATEGIES) == {"ema", "rsi", "smc"}
    assert all(ready for _cls, _label, ready in reg.STRATEGIES.values())


def test_the_labels_are_unchanged():
    """These strings are rendered in the builder's dropdown."""
    assert reg.strategy_label("ema") == "EMA Trend Bot"
    assert reg.strategy_label("rsi") == "RSI Scalper"
    assert reg.strategy_label("smc") == "SMC (Smart Money)"


def test_the_catalog_is_still_a_plain_dict_to_its_callers():
    """``app.py`` iterates it, ``bots/manager.py`` indexes it,
    ``services/regime.py`` calls ``.get`` — the swap must be invisible to all
    three."""
    assert isinstance(reg.STRATEGIES, dict)
    cls, label, ready = reg.STRATEGIES["ema"]
    assert reg.STRATEGIES.get("nope") is None
    assert (cls, label, ready) == reg.STRATEGIES["ema"]


def test_build_strategy_still_works_and_still_raises_valueerror():
    """Call sites catch ValueError. The registry's own UnknownStrategyError is a
    KeyError and would slip past them as a 500."""
    assert reg.build_strategy("ema", "BTCUSDT").symbol == "BTCUSDT"
    with pytest.raises(ValueError):
        reg.build_strategy("nope", "BTCUSDT")


def test_is_ready_strategy_still_answers():
    from bots.manager import is_ready_strategy
    assert is_ready_strategy("ema") is True
    assert is_ready_strategy("nope") is False


# ── every existing strategy survived the migration ──────────────────────────

def test_all_eight_built_in_strategies_are_installed():
    """Five of them were importable but unreachable before: they existed as
    files with no registry entry. Discovery is what makes them addressable at
    all — installed, documented and backtestable, without being offered as live
    bot options."""
    assert set(reg.registry().keys()) == {
        "ema", "rsi", "smc", "donchian", "supertrend", "ensemble", "brain",
        "custom"}


def test_every_strategy_inherits_the_plugin_base():
    for cls in reg.installed():
        assert issubclass(cls, BaseStrategy), f"{cls.__name__} is not a plugin"


def test_every_strategy_declares_a_version_and_a_description():
    for cls in reg.installed():
        assert cls.meta.version, cls.meta.key
        assert cls.meta.description, f"{cls.meta.key} has no description"


def test_every_strategy_declares_its_parameters():
    for cls in reg.installed():
        assert cls.parameters, f"{cls.meta.key} declares no parameters"


def test_no_strategy_hides_a_knob_from_the_ui():
    """An undeclared constructor argument is one no UI can render and no
    optimiser can sweep. Not fatal — but on the built-ins it should be zero, and
    a new one appearing should be a decision."""
    hidden = {c.meta.key: c.undeclared_parameters() for c in reg.installed()
              if c.undeclared_parameters()}
    assert hidden == {"custom": ("spec", "brain", "min_score", "on_block")}, (
        "custom takes collaborator objects, not tunable knobs, which is why it "
        f"declares requires=('spec',) and is not offerable. Others: {hidden}")


def test_the_unoffered_strategies_say_why():
    """A strategy kept out of the builder must be explicable, or it looks
    broken. Either it is not stable yet, or it cannot be built from a symbol."""
    for cls in reg.installed():
        if cls.meta.offerable:
            continue
        assert cls.meta.maturity is not Maturity.STABLE or cls.meta.requires, (
            f"{cls.meta.key} is stable and constructible but not offered — "
            "there is no reason left for it to be hidden")


def test_custom_cannot_be_built_from_a_key_and_a_symbol():
    """The reason it declares ``requires``. Offering it in the builder would put
    an option there that raises the moment it is chosen."""
    assert "custom" not in reg.STRATEGIES
    with pytest.raises(TypeError):
        reg.registry().build("custom", "BTCUSDT")


@pytest.mark.parametrize("key", ["ema", "rsi", "smc", "donchian", "supertrend",
                                 "ensemble", "brain"])
def test_every_offerable_shape_still_constructs_with_its_defaults(key):
    strategy = reg.registry().build(key, "BTCUSDT")
    assert strategy.symbol == "BTCUSDT"
    assert strategy.params, f"{key} lost its parameters through the migration"


@pytest.mark.parametrize("key", ["ema", "rsi", "smc", "donchian", "supertrend",
                                 "ensemble", "brain"])
def test_the_declared_defaults_match_what_construction_produces(key):
    """A declaration that disagrees with the constructor is worse than none,
    because it is believed: the UI shows one number and the bot runs another.

    Caught five real instances on its first run. ``smc``, ``donchian``,
    ``supertrend`` and ``ensemble`` all ``setdefault("rr_target", 2.5)`` in
    their constructors, and ``brain`` uses 3.0, while all five inherited a
    shared declaration saying 2.0 — so every one of them would have advertised a
    reward:risk target it does not use.
    """
    cls = reg.strategy_class(key)
    built = cls("BTCUSDT").params
    for name, value in cls.defaults().items():
        assert built[name] == value, f"{key}.{name}: declared {value}, built {built[name]}"


# ── the validation rules that used to live in constructors ──────────────────

def test_the_ema_ordering_rule_still_raises():
    with pytest.raises(ValueError):
        reg.build_strategy("ema", "BTCUSDT", fast=30, slow=10)


def test_the_rsi_ordering_rule_still_raises():
    with pytest.raises(ValueError):
        reg.build_strategy("rsi", "BTCUSDT", oversold=80, overbought=20)


def test_those_rules_are_now_answerable_without_constructing_anything():
    """The point of declaring them: a form can be checked before a strategy is
    built, and an optimiser can skip combinations that would raise instead of
    spending candidates on them."""
    result = reg.strategy_class("ema").validate_params({"fast": 30, "slow": 10})
    assert not result.ok and "below the slow" in result.explain()


# ── installing a plugin without touching the engine ─────────────────────────

def test_a_dropped_file_reaches_the_builder(tmp_path):
    """End to end, through the real catalog: a stable plugin appears in
    ``STRATEGIES`` — the dictionary the bot builder renders — with no edit to
    any engine module."""
    (tmp_path / "dropped.py").write_text(textwrap.dedent('''
        from typing import Optional
        from bot.types import Bar, Signal
        from tradexa.strategy import Maturity, StrategyMeta
        from strategies.base_strategy import ATR_PARAMETERS, HubStrategy

        class Dropped(HubStrategy):
            """Installed by being a file in a folder."""
            name = "dropped"
            label = "Dropped In"
            meta = StrategyMeta(key="dropped", name="Dropped In", version="1.0.0",
                                description="Proves the plugin path works.",
                                maturity=Maturity.STABLE)
            parameters = ATR_PARAMETERS

            def generate(self, bar: Bar) -> Optional[Signal]:
                return None
    '''))
    reg.PLUGINS_DIR = tmp_path
    reg.STRATEGIES.refresh()
    assert "dropped" in reg.STRATEGIES
    assert reg.strategy_label("dropped") == "Dropped In"
    assert reg.build_strategy("dropped", "BTCUSDT").params["atr_period"] == 14


def test_an_experimental_plugin_installs_without_being_offered(tmp_path):
    """Installed and studiable, not yet offered — the distinction a hardcoded
    list cannot express."""
    (tmp_path / "exp.py").write_text(textwrap.dedent('''
        from tradexa.strategy import Maturity, StrategyMeta
        from strategies.base_strategy import HubStrategy

        class Exp(HubStrategy):
            meta = StrategyMeta(key="exp", name="Exp", description="x",
                                maturity=Maturity.EXPERIMENTAL)
            def generate(self, bar): return None
    '''))
    reg.PLUGINS_DIR = tmp_path
    reg.STRATEGIES.refresh()
    assert "exp" in reg.registry()
    assert "exp" not in reg.STRATEGIES


def test_a_broken_plugin_does_not_break_the_catalog(tmp_path, capsys):
    """The live-bot property: one bad third-party file must not stop the
    strategies that bots are running from loading."""
    (tmp_path / "broken.py").write_text("this is not python\n")
    reg.PLUGINS_DIR = tmp_path
    reg.STRATEGIES.refresh()
    assert set(reg.STRATEGIES) == {"ema", "rsi", "smc"}
    assert any("broken.py" in e["source"] for e in reg.discovery_errors())
    assert "[plugins]" in capsys.readouterr().out, "the failure loaded silently"


def test_a_plugin_cannot_hijack_a_built_in_key(tmp_path):
    """Saved bot configurations resolve by key. A file dropped in a folder must
    not change which code an existing bot runs."""
    (tmp_path / "hijack.py").write_text(textwrap.dedent('''
        from tradexa.strategy import Maturity, StrategyMeta
        from strategies.base_strategy import HubStrategy

        class Hijack(HubStrategy):
            meta = StrategyMeta(key="ema", name="Not EMA", description="x",
                                maturity=Maturity.STABLE)
            def generate(self, bar): return None
    '''))
    reg.PLUGINS_DIR = tmp_path
    reg.STRATEGIES.refresh()
    assert reg.strategy_label("ema") == "EMA Trend Bot"
    assert any("ema" in e["message"] for e in reg.discovery_errors())


# ── the API ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    return TestClient(hub_app.app)


def _auth() -> dict:
    import app as hub_app
    return {"X-Webhook-Secret": hub_app.settings.webhook_secret}


def test_the_installed_endpoint_lists_every_plugin(client):
    body = client.get("/strategies/installed", headers=_auth()).json()
    assert {s["key"] for s in body["strategies"]} == set(reg.registry().keys())
    assert body["offerable"] == ["ema", "rsi", "smc"]
    assert body["errors"] == []


def test_the_detail_endpoint_returns_generated_documentation(client):
    body = client.get("/strategies/installed/ema", headers=_auth()).json()
    assert "# EMA Trend Bot" in body["documentation"]
    assert "`fast`" in body["documentation"]
    assert body["version"] == "1.0.0"


def test_the_documentation_is_about_the_strategy_not_the_base_class(client):
    """``inspect.getdoc`` walks the MRO, so a strategy without its own docstring
    documented itself with BaseStrategy's."""
    body = client.get("/strategies/installed/rsi", headers=_auth()).json()
    assert "contract every installable" not in body["documentation"]


def test_the_validate_endpoint_reports_every_problem(client):
    r = client.post("/strategies/installed/ema/validate", headers=_auth(),
                    json={"fast": 500, "slow": 1})
    body = r.json()
    assert body["ok"] is False
    assert len(body["issues"]) >= 2


def test_an_unknown_strategy_is_a_404_not_a_500(client):
    assert client.get("/strategies/installed/nope", headers=_auth()).status_code == 404


def test_the_plugin_endpoints_are_behind_the_auth_wall(client):
    for path in ("/strategies/installed", "/strategies/installed/ema"):
        assert client.get(path).status_code == 401, path
