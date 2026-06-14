"""Phase 4: per-bot analytics page."""
from bots.manager import BotManager
from dashboard.analytics import render_analytics
from database.models import BotConfig, BotMode


def _run_bot(m, name="EMA Trend Bot", strat="ema"):
    bot = m.create(BotConfig(name=name, strategy=strat, exchange="binance",
                             symbol="BTCUSDT", timeframe="1h", mode=BotMode.PAPER))
    m.start(bot.id)
    return bot


def test_analytics_empty_state():
    m = BotManager()
    out = render_analytics(m)
    assert "No completed runs" in out


def test_analytics_renders_charts_kpis_and_history():
    m = BotManager()
    bot = _run_bot(m)
    out = render_analytics(m, bot_id=bot.id)
    # KPI breakdown
    for kpi in ("Win rate", "Profit factor", "Avg RR", "Expectancy",
                "Sharpe / Sortino", "Max drawdown", "Best / Worst"):
        assert kpi in out
    # Two charts (equity + drawdown)
    assert out.count("<svg") >= 2
    # Trade history table present
    assert "Trade History" in out
    assert "Date/time" in out and "RR" in out


def test_analytics_defaults_to_first_bot_when_id_unknown():
    m = BotManager()
    b1 = _run_bot(m, name="Bot One")
    out = render_analytics(m, bot_id="does-not-exist")
    assert "Bot One" in out  # fell back to a real run


def test_analytics_selector_lists_run_bots():
    m = BotManager()
    _run_bot(m, name="Alpha")
    _run_bot(m, name="Beta", strat="rsi")
    out = render_analytics(m)
    assert "Select Bot" in out
    assert "Alpha" in out and "Beta" in out
