"""Phase 9: per-bot config editing + ad-hoc backtest."""
from bots.manager import BotManager
from dashboard.analytics import render_result
from database.models import BotConfig, BotMode, BotState, RiskRules
from database.store import SqliteStore


def _cfg(name="Bot", strat="ema"):
    return BotConfig(name=name, strategy=strat, exchange="binance",
                     symbol="BTCUSDT", timeframe="1h", mode=BotMode.PAPER)


# --------------------------------------------------------------- edit
def test_update_changes_config_and_persists(tmp_path):
    db = tmp_path / "hub.db"
    m = BotManager(store=SqliteStore(db))
    bot = m.create(_cfg())
    m.update(bot.id, name="Renamed", symbol="ETHUSDT", strategy="rsi",
             risk=RiskRules(risk_per_trade_pct=0.05, max_drawdown_pct=0.1))

    assert bot.config.name == "Renamed"
    assert bot.config.symbol == "ETHUSDT"
    assert bot.config.strategy == "rsi"

    # survives a reload
    reloaded = BotManager(store=SqliteStore(db)).get(bot.id)
    assert reloaded.config.name == "Renamed"
    assert reloaded.config.symbol == "ETHUSDT"
    assert reloaded.config.risk.risk_per_trade_pct == 0.05


def test_update_ignores_unknown_keys(tmp_path):
    m = BotManager(store=SqliteStore(tmp_path / "hub.db"))
    bot = m.create(_cfg())
    m.update(bot.id, bogus="x", name="Kept")
    assert bot.config.name == "Kept"
    assert not hasattr(bot.config, "bogus")


# ------------------------------------------------------------ backtest
def test_backtest_does_not_mutate_runtime():
    m = BotManager()
    bot = m.create(_cfg())
    assert bot.runtime.state == BotState.CREATED
    res = m.backtest(bot.id)
    assert "num_trades" in res.metrics
    assert res.equity_curve
    # state untouched by an ad-hoc backtest
    assert bot.runtime.state == BotState.CREATED
    assert bot.runtime.trades == []


def test_render_result_from_backtest():
    m = BotManager()
    bot = m.create(_cfg())
    res = m.backtest(bot.id)
    html = render_result(bot.config.name, res.metrics, res.trades, res.equity_curve)
    assert "Win rate" in html and "Trade History" in html
    assert html.count("<svg") >= 2          # equity + drawdown
