"""Strategy Health monitoring (Phase 3 · strategy quality)."""
from services.strategy_health import HealthConfig, StrategyHealthMonitor


def _trade(pnl, r=1.0):
    return {"pnl": pnl, "r": r}


def _wins(n):
    return [_trade(100, 2.0) for _ in range(n)]


def _losses(n):
    return [_trade(-100, -1.0) for _ in range(n)]


def test_healthy_strategy_no_warnings():
    mon = StrategyHealthMonitor(HealthConfig(window=10, min_sample=5))
    trades = _wins(8) + _losses(2) + _wins(8) + _losses(2)
    h = mon.evaluate(trades)
    assert h.status == "Healthy" and not h.warnings
    assert h.recent.n == 10 and 0 <= h.recent.win_rate <= 1


def test_losing_recent_window_is_unhealthy():
    mon = StrategyHealthMonitor(HealthConfig(window=10, min_sample=5))
    trades = _wins(10) + _losses(8) + _wins(2)   # recent 10 mostly losses -> PF < 1
    h = mon.evaluate(trades)
    assert h.status == "Unhealthy"
    assert any(w.metric == "profit_factor" and w.severity == "critical" for w in h.warnings)


def test_win_rate_decline_warns():
    mon = StrategyHealthMonitor(HealthConfig(window=10, min_sample=5, win_rate_drop=0.2))
    previous = _wins(9) + _losses(1)             # 90% win
    recent = _wins(5) + _losses(5)               # 50% win, but still PF>=1
    h = mon.evaluate(previous + recent)
    assert h.status in ("Degrading", "Unhealthy")
    assert any(w.metric == "win_rate" for w in h.warnings)


def test_consecutive_losses_warns():
    mon = StrategyHealthMonitor(HealthConfig(window=12, min_sample=4, max_consecutive_losses=5))
    trades = _wins(6) + _losses(6)               # 6 trailing losses
    h = mon.evaluate(trades)
    assert any(w.metric == "consecutive_losses" for w in h.warnings)


def test_small_sample_does_not_warn():
    mon = StrategyHealthMonitor(HealthConfig(min_sample=8))
    h = mon.evaluate(_losses(3))                 # too few trades
    assert h.status == "Healthy" and not h.warnings


def test_runner_reports_strategy_health():
    from bot.data.synthetic import generate_bars
    from bots.manager import BotManager
    from data.websocket import ReplayFeed
    from database.models import BotConfig, BotMode
    m = BotManager()
    bot = m.create(BotConfig(name="EMA", strategy="ema", exchange="binance",
                             symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE))
    m.start_live(bot.id, feed=ReplayFeed(generate_bars(400, "1h", seed=4)))
    m.runner(bot.id).wait(timeout=15)
    sh = bot.runtime.strategy_health
    assert sh["status"] in ("Healthy", "Degrading", "Unhealthy")
    assert "recent" in sh and "warnings" in sh
