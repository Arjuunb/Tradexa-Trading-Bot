"""Phase 6: SQLite persistence — bots survive a 'restart'."""
from bots.manager import BotManager
from database.models import BotConfig, BotMode, BotState, RiskRules
from database.store import SqliteStore


def _cfg(name="Persisted", strat="ema"):
    return BotConfig(name=name, strategy=strat, exchange="binance",
                     symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE,
                     risk=RiskRules(risk_per_trade_pct=0.02, max_drawdown_pct=0.15))


def test_bot_survives_restart(tmp_path):
    db = tmp_path / "hub.db"
    m = BotManager(store=SqliteStore(db))
    bot = m.create(_cfg())
    bid = bot.id

    # "restart": brand-new store + manager on the same file
    m2 = BotManager(store=SqliteStore(db))
    bots = m2.list()
    assert len(bots) == 1
    loaded = bots[0]
    assert loaded.id == bid
    assert loaded.config.name == "Persisted"
    assert loaded.config.strategy == "ema"
    assert loaded.config.mode == BotMode.LIVE
    assert loaded.config.risk.risk_per_trade_pct == 0.02   # RiskRules round-tripped
    assert loaded.config.risk.max_drawdown_pct == 0.15


def test_delete_is_persisted(tmp_path):
    db = tmp_path / "hub.db"
    m = BotManager(store=SqliteStore(db))
    bot = m.create(_cfg(name="Temp"))
    m.delete(bot.id)
    assert BotManager(store=SqliteStore(db)).list() == []


def test_active_state_coerced_to_stopped_on_reload(tmp_path):
    db = tmp_path / "hub.db"
    m = BotManager(store=SqliteStore(db))
    bot = m.create(_cfg(name="Runner"))
    m.start(bot.id)                       # mode LIVE -> RUNNING, persisted
    assert bot.runtime.state == BotState.RUNNING

    reloaded = BotManager(store=SqliteStore(db)).list()[0]
    assert reloaded.runtime.state == BotState.STOPPED   # threads don't survive


def test_migrations_apply_once(tmp_path):
    db = tmp_path / "hub.db"
    SqliteStore(db).close()
    store = SqliteStore(db)               # second open: must not re-apply
    rows = list(store._conn.execute("SELECT version FROM _migrations"))
    assert len(rows) == 1
    assert rows[0]["version"] == "0001_init"


def test_in_memory_manager_unchanged_without_store():
    # Backward compatibility: no store == pure in-memory (Phases 1-5 behaviour).
    m = BotManager()
    m.create(_cfg())
    assert len(m.list()) == 1
    assert m._store is None
