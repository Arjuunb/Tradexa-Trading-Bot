"""Persistent favorites, pins and watchlists.

Survives logout / restart (kept under HUB_DATA_DIR, like the paper account). A
single JSON document is enough — the workspace is owner-centric, matching the
paper account — so this stays a tiny, dependency-free store:

    {"favorites": ["BTCUSDT", "AAPL"],          # starred symbols
     "pinned":    ["BTCUSDT"],                    # pinned subset (ordered)
     "watchlists":[{"id": "...", "name": "Crypto", "symbols": ["BTCUSDT", ...]}]}
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from services.tenancy import OWNER_TENANT


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


_EMPTY = {"favorites": [], "pinned": [], "watchlists": []}


class WatchlistStore:
    """Per-tenant favorites/pins/watchlists. Phase C-1: keyed by ``tenant_id``
    (default ``OWNER_TENANT``), so single-owner behaviour is identical while the
    schema is isolation-ready. The old singleton (``id=1``) row is migrated to the
    owner tenant on first open."""

    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._migrate()

    # ------------------------------------------------------------- migration
    def _migrate(self) -> None:
        cols = [r[1] for r in self._c.execute("PRAGMA table_info(market_prefs)").fetchall()]
        if cols and "tenant_id" not in cols:
            # legacy singleton schema (id=1) -> tenant-keyed; preserve the one row
            old = self._c.execute("SELECT data, updated_at FROM market_prefs WHERE id = 1").fetchone()
            self._c.execute("ALTER TABLE market_prefs RENAME TO market_prefs_legacy")
            self._c.execute(
                """CREATE TABLE market_prefs (
                       tenant_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT)""")
            if old:
                self._c.execute(
                    "INSERT INTO market_prefs(tenant_id, data, updated_at) VALUES (?, ?, ?)",
                    (OWNER_TENANT, old[0], old[1]))
            self._c.execute("DROP TABLE market_prefs_legacy")
        else:
            self._c.execute(
                """CREATE TABLE IF NOT EXISTS market_prefs (
                       tenant_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT)""")
        self._c.commit()

    # ------------------------------------------------------------- internals
    def _read(self, tenant: str) -> dict:
        r = self._c.execute("SELECT data FROM market_prefs WHERE tenant_id = ?", (tenant,)).fetchone()
        if not r:
            return json.loads(json.dumps(_EMPTY))
        try:
            d = json.loads(r[0])
        except Exception:  # noqa: BLE001
            return json.loads(json.dumps(_EMPTY))
        for k, v in _EMPTY.items():
            d.setdefault(k, json.loads(json.dumps(v)))
        return d

    def _write(self, tenant: str, d: dict) -> dict:
        self._c.execute(
            "INSERT OR REPLACE INTO market_prefs(tenant_id, data, updated_at) VALUES (?, ?, ?)",
            (tenant, json.dumps(d), _utcnow()))
        self._c.commit()
        return d

    # ------------------------------------------------------------- reads
    # Every method takes an optional ``tenant`` (default OWNER_TENANT). Callers in
    # single-owner mode pass nothing → identical behaviour; the request layer will
    # pass resolve_tenant(user) once HUB_MULTI_USER is on.
    def get(self, tenant: str = OWNER_TENANT) -> dict:
        with self._lock:
            return self._read(tenant)

    # ------------------------------------------------------------- favorites
    def set_favorite(self, symbol: str, on: bool, tenant: str = OWNER_TENANT) -> dict:
        sym = (symbol or "").strip().upper()
        with self._lock:
            d = self._read(tenant)
            favs = [f for f in d["favorites"] if f != sym]
            if on:
                favs.append(sym)
            else:
                d["pinned"] = [p for p in d["pinned"] if p != sym]   # unfavorite unpins
            d["favorites"] = favs
            return self._write(tenant, d)

    def set_pin(self, symbol: str, on: bool, tenant: str = OWNER_TENANT) -> dict:
        sym = (symbol or "").strip().upper()
        with self._lock:
            d = self._read(tenant)
            pins = [p for p in d["pinned"] if p != sym]
            if on:
                pins.insert(0, sym)
                if sym not in d["favorites"]:      # pinning implies favoriting
                    d["favorites"].append(sym)
            d["pinned"] = pins
            return self._write(tenant, d)

    # ------------------------------------------------------------- watchlists
    def create_watchlist(self, name: str, symbols: Optional[list[str]] = None,
                         tenant: str = OWNER_TENANT) -> dict:
        with self._lock:
            d = self._read(tenant)
            wl = {"id": uuid.uuid4().hex[:12], "name": (name or "Watchlist").strip(),
                  "symbols": [s.strip().upper() for s in (symbols or []) if s.strip()]}
            d["watchlists"].append(wl)
            return self._write(tenant, d)

    def rename_watchlist(self, wid: str, name: str, tenant: str = OWNER_TENANT) -> dict:
        with self._lock:
            d = self._read(tenant)
            for wl in d["watchlists"]:
                if wl["id"] == wid:
                    wl["name"] = (name or wl["name"]).strip()
            return self._write(tenant, d)

    def delete_watchlist(self, wid: str, tenant: str = OWNER_TENANT) -> dict:
        with self._lock:
            d = self._read(tenant)
            d["watchlists"] = [wl for wl in d["watchlists"] if wl["id"] != wid]
            return self._write(tenant, d)

    def set_watchlist_symbol(self, wid: str, symbol: str, on: bool,
                            tenant: str = OWNER_TENANT) -> dict:
        sym = (symbol or "").strip().upper()
        with self._lock:
            d = self._read(tenant)
            for wl in d["watchlists"]:
                if wl["id"] == wid:
                    syms = [s for s in wl["symbols"] if s != sym]
                    if on:
                        syms.append(sym)
                    wl["symbols"] = syms
            return self._write(tenant, d)
