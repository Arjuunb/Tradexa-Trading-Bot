"""Phase C-3: the flat-table stores are tenant-namespaced (schema only).

Every flat SQLite store now runs ``ensure_tenant_column`` at open, so its tables
gain a ``tenant_id`` column defaulting to the owner and existing rows are
backfilled. This is the *expand* half of expand-migrate-contract: additive and
behaviour-preserving — reads do NOT filter by tenant yet, so single-owner
behaviour is byte-for-byte unchanged. These tests prove both: the column exists
(and defaults/backfills to the owner) AND the stores still read/write as before.
"""
import sqlite3

from services.tenancy import OWNER_TENANT
from data.ledger import SqliteLedger
from data.cycle_store import CycleStore
from data.decision_store import DecisionStore
from data.skipped_store import SkippedTradeStore
from data.trade_memory_store import TradeMemoryStore
from data.journal_store import JournalStore


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _owner_count(conn, table):
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", (OWNER_TENANT,)).fetchone()[0]


# ---------------------------------------------------------------- ledger (5 tables)
def test_ledger_tables_are_tenant_namespaced(tmp_path):
    led = SqliteLedger(str(tmp_path / "ledger.db"))
    for t in ("webhook_events", "positions", "paper_trades", "bot_logs", "alerts"):
        assert "tenant_id" in _cols(led._c, t), t

    # behaviour unchanged: a normal write/read round-trips, and the new row is
    # stamped to the owner by the column DEFAULT (no code passes tenant yet).
    tid = led.record_paper_trade({
        "symbol": "BTCUSDT", "side": "long", "size": 1.0, "entry": 100.0,
        "stop": 90.0, "status": "open", "source": "paper",
    })
    trades = led.get_paper_trades()
    assert any(t["id"] == tid for t in trades)
    assert _owner_count(led._c, "paper_trades") == 1        # defaulted to owner


def test_ledger_backfills_legacy_rows_to_owner(tmp_path):
    db = str(tmp_path / "legacy_ledger.db")
    # build a legacy row on the OLD schema (no tenant_id) …
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE alerts (id TEXT PRIMARY KEY, ts TEXT NOT NULL, severity TEXT NOT NULL,"
        " category TEXT NOT NULL, title TEXT NOT NULL, detail TEXT, read INTEGER NOT NULL DEFAULT 0);")
    c.execute("INSERT INTO alerts(id,ts,severity,category,title) VALUES ('a','t','info','system','hi')")
    c.commit(); c.close()
    # … opening the ledger migrates it: column added, existing row backfilled to owner
    led = SqliteLedger(db)
    assert "tenant_id" in _cols(led._c, "alerts")
    assert _owner_count(led._c, "alerts") == 1


# ---------------------------------------------------------------- the other stores
def test_cycle_decision_skipped_have_tenant_column(tmp_path):
    cs = CycleStore(str(tmp_path / "c.db"))
    ds = DecisionStore(str(tmp_path / "d.db"))
    ss = SkippedTradeStore(str(tmp_path / "s.db"))
    assert "tenant_id" in _cols(cs._c, "cycle_reports")
    assert "tenant_id" in _cols(ds._c, "decisions")
    assert "tenant_id" in _cols(ss._c, "skipped_trades")

    # behaviour unchanged: record + read still works, row defaults to owner
    cs.record({"ts": "t", "symbol": "BTCUSDT", "timeframe": "1h",
               "price": 100.0, "decision": "WAIT", "score": 0})
    assert _owner_count(cs._c, "cycle_reports") == 1


def test_trade_memory_and_journal_have_tenant_column(tmp_path):
    tm = TradeMemoryStore(str(tmp_path / "m.db"))
    jr = JournalStore(str(tmp_path / "j.db"))
    for t in ("trade_memories", "memory_reviews"):
        assert "tenant_id" in _cols(tm._c, t), t
    for t in ("trade_decision_journal", "trade_decision_events", "evolution_memory"):
        assert "tenant_id" in _cols(jr._c, t), t


def test_reopen_is_idempotent(tmp_path):
    db = str(tmp_path / "c.db")
    CycleStore(db)                       # first open adds the column
    cs2 = CycleStore(db)                 # second open must be a no-op, not error
    assert "tenant_id" in _cols(cs2._c, "cycle_reports")
