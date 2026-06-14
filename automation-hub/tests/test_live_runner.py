"""Phase 2: live runner streams bars through the engine on a background thread."""
from bot.backtester import Backtester
from bot.data.synthetic import generate_bars

from bots.manager import BotManager
from bots.registry import build_strategy
from data.websocket import ReplayFeed
from database.models import BotConfig, BotMode, BotState


def _bot():
    return BotConfig(name="EMA Live", strategy="ema", exchange="binance",
                     symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE)


def test_live_runner_streams_and_finishes():
    bars = generate_bars(400, "1h", seed=4)
    m = BotManager()
    bot = m.create(_bot())
    m.start_live(bot.id, feed=ReplayFeed(bars))

    runner = m.runner(bot.id)
    assert runner is not None
    runner.wait(timeout=15)             # finite replay feed -> thread ends

    rt = bot.runtime
    assert rt.state == BotState.STOPPED
    assert "num_trades" in rt.metrics
    assert rt.equity_curve                      # populated live
    assert len(rt.equity_curve) == len(bars)    # one snapshot per streamed bar


def test_live_run_matches_batch_backtest():
    """A replay-driven live run must equal a batch backtest of the same bars."""
    bars = generate_bars(400, "1h", seed=4)
    m = BotManager()
    bot = m.create(_bot())
    m.start_live(bot.id, feed=ReplayFeed(bars))
    m.runner(bot.id).wait(timeout=15)

    batch = Backtester(build_strategy("ema", "BTCUSDT"), list(bars)).run()
    assert bot.runtime.metrics["num_trades"] == batch.metrics["num_trades"]
    assert bot.runtime.equity_curve[-1][1] == batch.ending_equity


def test_risk_breaker_halts_live_bot():
    """A tight drawdown/consecutive-loss cap must trip and auto-halt the bot."""
    from database.models import RiskRules
    bars = generate_bars(500, "1h", seed=4)
    m = BotManager()
    cfg = BotConfig(name="EMA Live", strategy="ema", exchange="binance",
                    symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE,
                    risk=RiskRules(max_drawdown_pct=0.0005, max_consecutive_losses=1))
    bot = m.create(cfg)
    m.start_live(bot.id, feed=ReplayFeed(bars))
    m.runner(bot.id).wait(timeout=15)

    assert bot.runtime.state == BotState.STOPPED
    assert bot.runtime.halt_reason          # a breaker tripped
    # Halted early, before consuming all 500 bars.
    assert len(bot.runtime.equity_curve) < len(bars)


def test_stop_halts_runner():
    bars = generate_bars(2000, "1h", seed=9)
    m = BotManager()
    bot = m.create(_bot())
    # slow feed so it's still streaming when we stop it
    m.start_live(bot.id, feed=ReplayFeed(bars, delay_s=0.01))
    m.stop(bot.id)
    assert bot.runtime.state == BotState.STOPPED
    assert m.runner(bot.id) is None
