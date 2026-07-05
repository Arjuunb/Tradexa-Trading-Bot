"""Live performance summary computed from real executed trades."""
from services.performance import summarize


def _t(pnl, closed_at):
    return {"pnl": pnl, "closed_at": closed_at, "symbol": "BTCUSDT", "side": "long"}


def test_summarize_basic_stats():
    trades = [_t(100, "2026-01-01"), _t(-50, "2026-01-02"),
              _t(-50, "2026-01-03"), _t(200, "2026-01-04")]
    s = summarize(trades, 10_000)
    assert s["trades"] == 4
    assert s["win_rate"] == 50.0
    assert s["profit_factor"] == 3.0          # gross win 300 / gross loss 100
    assert s["realized_pnl"] == 200
    assert s["balance"] == 10_200
    assert s["longest_losing_streak"] == 2     # the two -50s in a row
    # equity curve includes the starting point + one per trade
    assert len(s["equity_curve"]) == 5
    assert s["equity_curve"][0]["equity"] == 10_000
    assert s["equity_curve"][-1]["equity"] == 10_200


def test_summarize_drawdown():
    # up to 10,300 then down to 9,800 -> max drawdown 500 (~4.85%)
    trades = [_t(300, "1"), _t(-500, "2"), _t(100, "3")]
    s = summarize(trades, 10_000)
    assert s["max_drawdown_abs"] == 500
    assert 4.0 < s["max_drawdown_pct"] < 5.0


def test_summarize_empty():
    s = summarize([], 10_000)
    assert s["trades"] == 0 and s["balance"] == 10_000
    assert s["equity_curve"] == [{"t": None, "equity": 10_000}]
    # risk-adjusted ratios are honestly zero with no sample
    assert s["sharpe_ratio"] == 0.0 and s["sortino_ratio"] == 0.0


def _tr(pnl, rr, closed_at):
    return {"pnl": pnl, "rr": rr, "closed_at": closed_at, "symbol": "BTCUSDT", "side": "long"}


def test_sharpe_sortino_from_real_r_multiples():
    trades = [_tr(100, 2.0, "1"), _tr(-50, -1.0, "2"), _tr(150, 3.0, "3"), _tr(-50, -1.0, "4")]
    s = summarize(trades, 10_000)
    # per-trade Sharpe = mean(R)/std(R); Sortino = mean(R)/downside-dev(R)
    assert s["sharpe_ratio"] > 0 and s["sortino_ratio"] > 0
    # Sortino > Sharpe here (upside vol doesn't penalise Sortino)
    assert s["sortino_ratio"] > s["sharpe_ratio"]
    assert s["risk_adjusted"]["basis"] == "per-trade R"
    assert s["risk_adjusted"]["sample"] == 4


def test_risk_adjusted_needs_two_trades():
    s = summarize([_tr(100, 2.0, "1")], 10_000)
    assert s["sharpe_ratio"] == 0.0 and s["risk_adjusted"]["sample"] == 1
