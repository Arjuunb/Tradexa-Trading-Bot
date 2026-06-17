"""Safety-flow logic: progression, risk validation, live checklist."""
from __future__ import annotations

from trading_bot.safety import gates


def test_progression_order():
    assert gates.PROGRESSION == ["Backtest", "Simulation", "Paper Trading", "Live Trading"]


def test_risk_valid():
    assert gates.risk_valid({"risk_per_trade_pct": 0.01, "max_drawdown_pct": 20, "max_open_positions": 5})
    assert not gates.risk_valid({})
    assert not gates.risk_valid({"risk_per_trade_pct": 0.10, "max_drawdown_pct": 20, "max_open_positions": 5})
    assert not gates.risk_valid({"risk_per_trade_pct": 0.01, "max_drawdown_pct": 0, "max_open_positions": 5})
    assert not gates.risk_valid({"risk_per_trade_pct": 0.01, "max_drawdown_pct": 20, "max_open_positions": 0})


def _kw(**over):
    base = dict(has_backtest=True, has_simulation=True, has_paper=True,
                risk_ok=True, broker_connected=True, user_confirmed=True)
    base.update(over)
    return base


def test_live_allowed_all_pass():
    assert gates.live_allowed(**_kw())


def test_live_blocked_without_broker():
    assert not gates.live_allowed(**_kw(broker_connected=False))


def test_live_blocked_without_each_stage():
    for missing in ("has_backtest", "has_simulation", "has_paper", "risk_ok", "user_confirmed"):
        assert not gates.live_allowed(**_kw(**{missing: False})), missing


def test_live_checklist_items():
    items, passed = gates.live_checklist(**_kw(has_paper=False))
    assert not passed
    assert ("Paper-trading performance", False) in items
