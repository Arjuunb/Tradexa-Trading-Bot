"""Market Regime Detection (Phase 4)."""
import datetime as dt

from bot.types import Bar

from services.regime import (
    RegimeDetector, RegimeGate, regime_allows, supported_for,
)

T0 = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)


def _bars(closes, rng=0.002):
    out = []
    for i, c in enumerate(closes):
        h = c * (1 + rng)
        lo = c * (1 - rng)
        out.append(Bar(T0 + dt.timedelta(hours=i), c, h, lo, c, 100.0))
    return out


def test_trending_market_detected():
    closes = [100 * (1.01 ** i) for i in range(60)]   # steady uptrend
    r = RegimeDetector().detect(_bars(closes))
    assert r.name == "Trending" and r.trend_strength > 0.9


def test_ranging_market_detected():
    closes = [100 + (0.3 if i % 2 == 0 else -0.3) for i in range(60)]  # small oscillation
    r = RegimeDetector().detect(_bars(closes, rng=0.002))
    assert r.name in ("Ranging", "Low Volatility") and r.trend_strength < 0.3


def test_extreme_volatility_detected():
    closes = [100 + (8 if i % 2 == 0 else -8) for i in range(60)]
    r = RegimeDetector().detect(_bars(closes, rng=0.06))   # huge bar ranges
    assert r.name == "Extreme Volatility"


def test_insufficient_data_defaults_ranging():
    r = RegimeDetector().detect(_bars([100, 101, 102]))
    assert r.name == "Ranging"


def test_regime_allows_and_supported_for():
    assert regime_allows((), "Trending")                  # no constraint -> any
    assert regime_allows(("Trending",), "Trending")
    assert not regime_allows(("Trending",), "Ranging")
    assert supported_for("ema") == ("Trending",)
    assert "Ranging" in supported_for("rsi")


def test_regime_gate_rejects_unsupported():
    gate = RegimeGate()
    trending = _bars([100 * (1.01 ** i) for i in range(60)])
    # EMA supports Trending -> allowed
    assert gate.check("ema", trending).allowed
    # RSI supports Ranging/Low-Vol -> rejected in a trending market
    v = gate.check("rsi", trending)
    assert not v.allowed and "not supported" in v.reason


def test_runner_reports_regime():
    from bot.data.synthetic import generate_bars
    from bots.manager import BotManager
    from data.websocket import ReplayFeed
    from database.models import BotConfig, BotMode
    m = BotManager()
    bot = m.create(BotConfig(name="EMA", strategy="ema", exchange="binance",
                             symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE))
    m.start_live(bot.id, feed=ReplayFeed(generate_bars(400, "1h", seed=4)))
    m.runner(bot.id).wait(timeout=15)
    reg = bot.runtime.regime
    assert reg["name"] in ("Trending", "Ranging", "High Volatility", "Low Volatility", "Extreme Volatility")
