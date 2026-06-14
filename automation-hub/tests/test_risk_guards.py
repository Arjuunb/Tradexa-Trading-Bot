"""Risk circuit-breaker (risk.guards) unit tests."""
from database.models import RiskRules
from risk import guards


def _rules(**kw) -> RiskRules:
    base = dict(max_daily_loss_pct=0.03, max_drawdown_pct=0.20,
                max_consecutive_losses=3)
    base.update(kw)
    return RiskRules(**base)


def test_no_trip_within_limits():
    trip = guards.evaluate(
        equity_curve=[100.0, 101.0, 100.5], trades=[{"pnl": 5}, {"pnl": -1}],
        pnl_today=4.0, starting_equity=10_000.0, rules=_rules(),
    )
    assert trip is None


def test_daily_loss_breaker():
    trip = guards.evaluate(
        equity_curve=[10_000.0, 9_700.0], trades=[], pnl_today=-301.0,
        starting_equity=10_000.0, rules=_rules(),  # 3% of 10k = 300
    )
    assert trip is not None and trip.breaker == "daily_loss"


def test_drawdown_breaker():
    # 100 -> 110 -> 80 == -27% drawdown, cap 20%
    trip = guards.evaluate(
        equity_curve=[(0, 100.0), (1, 110.0), (2, 80.0)], trades=[],
        pnl_today=0.0, starting_equity=100.0, rules=_rules(),
    )
    assert trip is not None and trip.breaker == "drawdown"


def test_consecutive_loss_breaker():
    trip = guards.evaluate(
        equity_curve=[100.0, 100.0], trades=[{"pnl": -1}, {"pnl": -2}, {"pnl": -3}],
        pnl_today=-6.0, starting_equity=10_000.0,
        rules=_rules(max_daily_loss_pct=0.5),   # keep daily-loss from firing first
    )
    assert trip is not None and trip.breaker == "consecutive_losses"


def test_daily_loss_takes_priority():
    # Both daily-loss and consecutive would trip; daily-loss is checked first.
    trip = guards.evaluate(
        equity_curve=[10_000.0, 9_000.0], trades=[{"pnl": -1}] * 5,
        pnl_today=-500.0, starting_equity=10_000.0, rules=_rules(),
    )
    assert trip.breaker == "daily_loss"
