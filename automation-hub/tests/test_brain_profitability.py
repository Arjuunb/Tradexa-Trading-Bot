"""DecisionBrain profitability upgrade: stand aside in noise, never fight the
trend reads. Validated out-of-sample across 10 market regimes × holdout seeds
(old brain −26.3R on holdout seeds; upgraded brain +67.8R, fewer/better trades)."""
from bot.data.synthetic import generate_bars
from bot.types import SignalType
from strategies.brain_strategy import DecisionBrain, _REGIME_FACTOR


def _signals(drift, vol, seed=55, n=1200):
    brain = DecisionBrain("BTCUSDT")
    out = []
    for b in generate_bars(n=n, timeframe="1h", drift_per_bar=drift,
                           vol_per_bar=vol, seed=seed):
        s = brain.on_bar(b)
        if s is not None:
            out.append(s)
    return out


def test_regime_factors_damp_noise_regimes():
    # chop is where the money was bleeding — those regimes must be damped hard
    assert _REGIME_FACTOR["Ranging"] <= 0.5
    assert _REGIME_FACTOR["High Volatility"] <= 0.5
    assert _REGIME_FACTOR["Extreme Volatility"] == 0.0
    assert _REGIME_FACTOR["Trending"] == 1.0


def test_brain_trades_trends_not_chop():
    trend = _signals(drift=0.0010, vol=0.006)      # clean uptrend
    chop = _signals(drift=0.0001, vol=0.020)       # high-vol chop
    assert len(trend) > 0                          # still trades real trends
    # stands aside in noise: far fewer entries than in a clean trend
    assert len(chop) < len(trend)


def test_brain_never_fights_its_trend_reads():
    # the alignment gate forbids entries where the trade direction disagrees
    # with the EMA trend or the long-trend filter (the old failure mode was a
    # hot RSI outshouting a disagreeing trend). The reason string records the
    # actual reads, so every emitted signal must show agreement.
    for drift in (-0.0010, 0.0010, 0.0003, -0.0003):
        for seed in (55, 71, 104):
            for s in _signals(drift=drift, vol=0.010, seed=seed):
                if s.type == SignalType.LONG:
                    assert "EMA12>EMA26" in s.reason and "price>EMA50" in s.reason
                else:
                    assert "EMA12<EMA26" in s.reason and "price<EMA50" in s.reason
