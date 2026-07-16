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


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


_EMPTY = {"favorites": [], "pinned": [], "watchlists": []}


class WatchlistStore:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.execute(
            """CREATE TABLE IF NOT EXISTS market_prefs (
                   id INTEGER PRIMARY KEY CHECK (id = 1),
                   data TEXT NOT NULL,
                   updated_at TEXT
               )""")
        self._c.commit()

    # ------------------------------------------------------------- internals
    def _read(self) -> dict:
        r = self._c.execute("SELECT data FROM market_prefs WHERE id = 1").fetchone()
        if not r:
            return json.loads(json.dumps(_EMPTY))
        try:
            d = json.loads(r[0])
        except Exception:  # noqa: BLE001
            return json.loads(json.dumps(_EMPTY))
        for k, v in _EMPTY.items():
            d.setdefault(k, json.loads(json.dumps(v)))
        return d

    def _write(self, d: dict) -> dict:
        self._c.execute(
            "INSERT OR REPLACE INTO market_prefs(id, data, updated_at) VALUES (1, ?, ?)",
            (json.dumps(d), _utcnow()))
        self._c.commit()
        return d

    # ------------------------------------------------------------- reads
    def get(self) -> dict:
        with self._lock:
            return self._read()

    # ------------------------------------------------------------- favorites
    def set_favorite(self, symbol: str, on: bool) -> dict:
        sym = (symbol or "").strip().upper()
        with self._lock:
            d = self._read()
            favs = [f for f in d["favorites"] if f != sym]
            if on:
                favs.append(sym)
            else:
                d["pinned"] = [p for p in d["pinned"] if p != sym]   # unfavorite unpins
            d["favorites"] = favs
            return self._write(d)

    def set_pin(self, symbol: str, on: bool) -> dict:
        sym = (symbol or "").strip().upper()
        with self._lock:
            d = self._read()
            pins = [p for p in d["pinned"] if p != sym]
            if on:
                pins.insert(0, sym)
                if sym not in d["favorites"]:      # pinning implies favoriting
                    d["favorites"].append(sym)
            d["pinned"] = pins
            return self._write(d)

    # ------------------------------------------------------------- watchlists
    def create_watchlist(self, name: str, symbols: Optional[list[str]] = None) -> dict:
        with self._lock:
            d = self._read()
            wl = {"id": uuid.uuid4().hex[:12], "name": (name or "Watchlist").strip(),
                  "symbols": [s.strip().upper() for s in (symbols or []) if s.strip()]}
            d["watchlists"].append(wl)
            return self._write(d)

    def rename_watchlist(self, wid: str, name: str) -> dict:
        with self._lock:
            d = self._read()
            for wl in d["watchlists"]:
                if wl["id"] == wid:
                    wl["name"] = (name or wl["name"]).strip()
            return self._write(d)

    def delete_watchlist(self, wid: str) -> dict:
        with self._lock:
            d = self._read()
            d["watchlists"] = [wl for wl in d["watchlists"] if wl["id"] != wid]
            return self._write(d)

    def set_watchlist_symbol(self, wid: str, symbol: str, on: bool) -> dict:
        sym = (symbol or "").strip().upper()
        with self._lock:
            d = self._read()
            for wl in d["watchlists"]:
                if wl["id"] == wid:
                    syms = [s for s in wl["symbols"] if s != sym]
                    if on:
                        syms.append(sym)
                    wl["symbols"] = syms
            return self._write(d)
