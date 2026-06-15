"""Adaptive Risk Management (Phase 6 · capital protection)."""
from services.adaptive_risk import AdaptiveConfig, AdaptiveRiskManager, current_drawdown


def test_current_drawdown_from_equity():
    assert current_drawdown([100, 120, 90]) == 0.25      # peak 120 -> 90
    assert current_drawdown([100, 110, 120]) == 0.0      # at new high


def test_modes_scale_with_drawdown():
    arm = AdaptiveRiskManager(AdaptiveConfig(defensive_dd=0.10, reduced_dd=0.15, pause_dd=0.20))
    assert arm.evaluate(0.05).name == "Normal" and arm.evaluate(0.05).size_multiplier == 1.0
    assert arm.evaluate(0.12).name == "Defensive" and arm.evaluate(0.12).size_multiplier == 0.5
    assert arm.evaluate(0.16).name == "Reduced" and arm.evaluate(0.16).size_multiplier == 0.25
    paused = arm.evaluate(0.22)
    assert paused.name == "Paused" and paused.size_multiplier == 0.0 and paused.paused


def test_volatility_spike_reduces_further():
    arm = AdaptiveRiskManager()
    normal = arm.evaluate(0.0, volatility_ratio=2.0)
    assert normal.name == "Defensive" and normal.size_multiplier == 0.5   # Normal -> Defensive on vol
    defensive = arm.evaluate(0.12, volatility_ratio=2.0)
    assert defensive.size_multiplier == 0.25                              # 0.5 * 0.5


def test_for_equity_helper():
    arm = AdaptiveRiskManager()
    mode = arm.for_equity([10000, 11000, 9000])                          # ~18% dd
    assert mode.name == "Reduced"


def test_runner_reports_risk_mode():
    from bot.data.synthetic import generate_bars
    from bots.manager import BotManager
    from data.websocket import ReplayFeed
    from database.models import BotConfig, BotMode
    m = BotManager()
    bot = m.create(BotConfig(name="EMA", strategy="ema", exchange="binance",
                             symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE))
    m.start_live(bot.id, feed=ReplayFeed(generate_bars(300, "1h", seed=4)))
    m.runner(bot.id).wait(timeout=15)
    rm = bot.runtime.risk_mode
    assert rm["name"] in ("Normal", "Defensive", "Reduced", "Paused")
    assert 0.0 <= rm["size_multiplier"] <= 1.0
