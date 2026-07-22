"""Phase C-1: multi-tenant foundation (behaviour-preserving).

Verifies the tenant seam, the reusable migration primitive, and that making the
watchlist store tenant-aware keeps single-owner behaviour identical while
migrating the legacy singleton row to the owner tenant.
"""
import os
import sqlite3

import pytest

from services.tenancy import OWNER_TENANT, multi_user_enabled, resolve_tenant, is_owner
from data.tenant_scope import ensure_tenant_column
from data.watchlist_store import WatchlistStore


# ---------------------------------------------------------------- seam
def test_resolve_tenant_single_owner_default(monkeypatch):
    monkeypatch.delenv("HUB_MULTI_USER", raising=False)
    assert not multi_user_enabled()
    assert resolve_tenant("anyuser") == OWNER_TENANT   # single-owner: everyone is the owner
    assert resolve_tenant(None) == OWNER_TENANT
    assert is_owner(resolve_tenant("x"))


def test_resolve_tenant_multi_user(monkeypatch):
    monkeypatch.setenv("HUB_MULTI_USER", "1")
    assert multi_user_enabled()
    assert resolve_tenant("arjun") == "arjun"          # multi-user: username is the tenant
    assert resolve_tenant(None) == OWNER_TENANT         # anonymous never leaks cross-tenant
    assert resolve_tenant("  ") == OWNER_TENANT


# ---------------------------------------------------------------- primitive
def test_ensure_tenant_column_idempotent_and_backfills(tmp_path):
    db = str(tmp_path / "t.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE trades (id TEXT PRIMARY KEY, pnl REAL)")
    c.execute("INSERT INTO trades VALUES ('a', 1.0), ('b', -2.0)")
    c.commit()
    assert ensure_tenant_column(c, "trades") is True          # added
    cols = [r[1] for r in c.execute("PRAGMA table_info(trades)")]
    assert "tenant_id" in cols
    owned = c.execute("SELECT COUNT(*) FROM trades WHERE tenant_id = ?", (OWNER_TENANT,)).fetchone()[0]
    assert owned == 2                                          # existing rows backfilled to owner
    assert ensure_tenant_column(c, "trades") is False         # idempotent
    assert ensure_tenant_column(c, "missing") is False        # no-op on absent table


# ---------------------------------------------------------------- store
def test_watchlist_single_owner_behaviour_unchanged(tmp_path):
    ws = WatchlistStore(str(tmp_path / "wl.db"))
    ws.set_favorite("btcusdt", True)                          # no tenant arg -> owner
    ws.set_pin("BTCUSDT", True)
    got = ws.get()                                            # no tenant arg -> owner
    assert "BTCUSDT" in got["favorites"] and got["pinned"] == ["BTCUSDT"]


def test_watchlist_tenants_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_MULTI_USER", "1")
    ws = WatchlistStore(str(tmp_path / "wl.db"))
    ws.set_favorite("BTCUSDT", True, tenant="alice")
    ws.set_favorite("ETHUSDT", True, tenant="bob")
    assert ws.get(tenant="alice")["favorites"] == ["BTCUSDT"]
    assert ws.get(tenant="bob")["favorites"] == ["ETHUSDT"]   # no cross-tenant bleed
    assert ws.get(tenant=OWNER_TENANT)["favorites"] == []


def test_watchlist_migrates_legacy_singleton_to_owner(tmp_path):
    db = str(tmp_path / "legacy.db")
    # build the OLD singleton schema with one row of real prefs
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE market_prefs (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, updated_at TEXT)")
    c.execute("INSERT INTO market_prefs(id, data, updated_at) VALUES (1, ?, ?)",
              ('{"favorites": ["SOLUSDT"], "pinned": [], "watchlists": []}', "t"))
    c.commit(); c.close()
    # opening the store migrates it to the tenant-keyed schema, owner keeps the data
    ws = WatchlistStore(db)
    cols = [r[1] for r in ws._c.execute("PRAGMA table_info(market_prefs)")]
    assert "tenant_id" in cols and "id" not in cols
    assert ws.get()["favorites"] == ["SOLUSDT"]              # owner sees the migrated row
