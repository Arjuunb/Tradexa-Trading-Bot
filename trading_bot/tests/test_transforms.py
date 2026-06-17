"""Pure chart transforms."""
from __future__ import annotations

from trading_bot.charts import transforms as tf


def test_equity_values_dict_and_list():
    assert tf.equity_values({"points": [{"equity": 1}, {"equity": 2}]}) == [1, 2]
    assert tf.equity_values([{"equity": 5}]) == [5]
    assert tf.equity_values(None) == []


def test_drawdown_series():
    assert tf.drawdown_series([100, 110, 105, 120]) == [0, 0, -5.0, 0]


def test_max_drawdown_pct():
    assert tf.max_drawdown_pct([100, 80]) == 20.0
    assert tf.max_drawdown_pct([]) == 0.0


def test_win_loss_counts():
    trades = [{"pnl": 5}, {"pnl": -2}, {"pnl": 0}, {"pnl": 3}]
    assert tf.win_loss_counts(trades) == (2, 1, 1)


def test_allocation_from_positions():
    labels, vals = tf.allocation_from_positions([{"symbol": "BTC", "size": 2, "entry": 100}])
    assert labels == ["BTC"]
    assert vals == [200.0]


def test_daily_pnl_groups_by_day():
    trades = [
        {"closed_at": "2026-01-01T10:00:00", "pnl": 5},
        {"closed_at": "2026-01-01T12:00:00", "pnl": 3},
        {"closed_at": "2026-01-02T09:00:00", "pnl": -4},
    ]
    days, pnls = tf.daily_pnl(trades)
    assert days == ["2026-01-01", "2026-01-02"]
    assert pnls == [8.0, -4.0]


def test_trade_r_distribution_empty():
    assert tf.trade_r_distribution([]) == ([], [])


def test_trade_r_distribution_bins():
    trades = [{"rr": r} for r in (-1, 0, 1, 2, 3)]
    labels, counts = tf.trade_r_distribution(trades, bins=4)
    assert len(labels) == 4
    assert sum(counts) == 5
