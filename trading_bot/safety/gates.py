"""Safety-first trading flow: Backtest -> Simulation -> Paper -> Live.

Pure logic (no UI) so it is fully testable. Live stays LOCKED until every gate
passes AND a live broker is actually connected.
"""
from __future__ import annotations

PROGRESSION = ["Backtest", "Simulation", "Paper Trading", "Live Trading"]


def risk_valid(editable: dict | None) -> bool:
    if not editable:
        return False
    r = editable
    return (0 < r.get("risk_per_trade_pct", 0) <= 0.05
            and r.get("max_drawdown_pct", 0) > 0
            and r.get("max_open_positions", 0) >= 1)


def live_checklist(*, has_backtest: bool, has_simulation: bool, has_paper: bool,
                   risk_ok: bool, broker_connected: bool, user_confirmed: bool):
    """Return (items, all_passed). Each item is (label, passed)."""
    items = [
        ("Valid backtest results", has_backtest),
        ("Simulation results recorded", has_simulation),
        ("Paper-trading performance", has_paper),
        ("Risk settings valid", risk_ok),
        ("Broker / exchange connected", broker_connected),
        ("Manual live confirmation", user_confirmed),
    ]
    return items, all(v for _, v in items)


def live_allowed(**kw) -> bool:
    _, ok = live_checklist(**kw)
    return ok
