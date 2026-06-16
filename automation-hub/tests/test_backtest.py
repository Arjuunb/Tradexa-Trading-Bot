"""Smoke tests for the DecisionBrain backtest / walk-forward harness."""
from backtest import Metrics, resample, run, walk_forward, _metrics
from data.market_data import get_bars


def test_run_produces_trades_and_metrics():
    bars, _ = get_bars("BTCUSDT", n=2000, timeframe="1h")
    rs = run(bars, threshold=0.4, rr=2.0)
    m = _metrics(rs)
    assert isinstance(m, Metrics)
    assert m.trades > 0
    assert m.profit_factor >= 0
    assert 0 <= m.win_rate <= 100


def test_resample_aggregates_bars():
    bars, _ = get_bars("BTCUSDT", n=160, timeframe="1h")
    r = resample(bars, 4)
    assert len(r) == 40
    # OHLC of an aggregated candle must be internally consistent
    assert r[0].high >= r[0].open and r[0].high >= r[0].close
    assert r[0].low <= r[0].open and r[0].low <= r[0].close


def test_metrics_math():
    m = _metrics([2.0, -1.0, 2.0, -1.0])   # 2 wins (+2), 2 losses (-1)
    assert m.trades == 4
    assert m.win_rate == 50.0
    assert round(m.profit_factor, 2) == 2.0   # gross 4 / gross loss 2
    assert round(m.net_r, 2) == 2.0


def test_walk_forward_returns_oos_metrics():
    bars, _ = get_bars("BTCUSDT", n=1600, timeframe="1h")
    agg, folds = walk_forward(bars, train=600, test=300)
    assert isinstance(agg, Metrics)
    assert len(folds) >= 1


def test_supertrend_and_donchian_strategies_run():
    bars, _ = get_bars("BTCUSDT", n=2000, timeframe="1h")
    for strat in ("supertrend", "donchian"):
        m = _metrics(run(bars, strategy=strat))
        assert isinstance(m, Metrics)
        assert m.trades > 0, f"{strat} produced no trades"
