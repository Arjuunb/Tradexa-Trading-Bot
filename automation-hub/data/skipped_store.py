"""Skipped-trade log — every setup the bot rejected, with the exact reason, the
gate that failed, and the market snapshot at the moment of rejection.

This is the mirror image of the decision journal: the journal explains trades
that happened; this explains trades that did NOT, so a "quiet" bot is never a
black box. Records come straight from the signal pipeline's reject() path — real
gate + real reason, never invented.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from data.tenant_scope import ensure_tenant_column


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# The pipeline gate (stage) that rejected a setup maps to a category so a skip is
# instantly classifiable: risk / quality / duplicate / session / safety / signal.
_CATEGORY = {
    "controls": "safety", "safety": "safety",
    "market_quality": "quality",
    "dedup": "duplicate",
    "session": "session", "trading_day": "session", "cooldown": "session",
    "risk_guard": "risk", "correlation": "risk", "daily_loss": "risk",
    "weekly_loss": "risk", "max_trades": "risk", "portfolio_exposure": "risk",
    "risk": "risk", "exposure": "risk", "event_risk": "risk",
    "learning": "signal", "context": "signal", "execution": "signal",
}


def category_for(stage: str) -> str:
    """Classify a failed gate. Unknown gates fall back to 'other' (never faked)."""
    return _CATEGORY.get(stage, "other")


class SkippedTradeStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.execute(
            """CREATE TABLE IF NOT EXISTS skipped_trades (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts TEXT NOT NULL,
                   symbol TEXT, side TEXT,
                   stage TEXT,          -- the gate that failed
                   status TEXT,         -- rejected / duplicate
                   reason TEXT,
                   entry REAL, stop REAL, target REAL,
                   strategy TEXT, timeframe TEXT,
                   snapshot_json TEXT
               )""")
        self._c.execute("CREATE INDEX IF NOT EXISTS ix_skipped_ts ON skipped_trades(ts)")
        self._c.execute("CREATE INDEX IF NOT EXISTS ix_skipped_stage ON skipped_trades(stage)")
        ensure_tenant_column(self._c, "skipped_trades")   # Phase C-3: schema-only, additive
        self._c.commit()

    def record(self, *, symbol: str, side: str, stage: str, reason: str,
               status: str = "rejected", entry: Optional[float] = None,
               stop: Optional[float] = None, target: Optional[float] = None,
               strategy: str = "", timeframe: str = "",
               snapshot: Optional[dict] = None) -> int:
        with self._lock:
            cur = self._c.execute(
                """INSERT INTO skipped_trades
                   (ts, symbol, side, stage, status, reason, entry, stop, target,
                    strategy, timeframe, snapshot_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_utcnow(), symbol, side, stage, status, reason, entry, stop, target,
                 strategy, timeframe, json.dumps(snapshot or {})))
            self._c.commit()
            return int(cur.lastrowid)

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["snapshot"] = json.loads(d.pop("snapshot_json") or "{}")
        d["category"] = category_for(d.get("stage", ""))
        return d

    def list(self, *, limit: int = 100, symbol: Optional[str] = None,
             stage: Optional[str] = None, q: Optional[str] = None) -> list[dict]:
        """Newest-first, filterable by symbol / failed gate, and free-text
        searchable across reason + symbol + stage."""
        sql = "SELECT * FROM skipped_trades"
        cond, args = [], []
        if symbol:
            cond.append("symbol = ?"); args.append(symbol.upper())
        if stage:
            cond.append("stage = ?"); args.append(stage)
        if q:
            cond.append("(reason LIKE ? OR symbol LIKE ? OR stage LIKE ?)")
            like = f"%{q}%"; args += [like, like, like]
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            return [self._row(r) for r in self._c.execute(sql, args)]

    def prune(self, keep: int = 20000) -> int:
        """Keep the most recent ``keep`` skipped-trade rows (by id); delete older."""
        with self._lock:
            cur = self._c.execute(
                "DELETE FROM skipped_trades WHERE id NOT IN "
                "(SELECT id FROM skipped_trades ORDER BY id DESC LIMIT ?)", (int(keep),))
            self._c.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def summary(self) -> list[dict]:
        """Count of skips per failed gate — where the bot says 'no' most."""
        with self._lock:
            return [dict(r) for r in self._c.execute(
                "SELECT stage, COUNT(*) AS count FROM skipped_trades "
                "GROUP BY stage ORDER BY count DESC")]

    def total(self) -> int:
        with self._lock:
            return int(self._c.execute("SELECT COUNT(*) FROM skipped_trades").fetchone()[0])

    def categories(self) -> list[dict]:
        """Skip counts rolled up by category (risk / quality / duplicate /
        session / safety / signal), derived from the real failed gate."""
        agg: dict[str, int] = {}
        for row in self.summary():
            agg[category_for(row["stage"])] = agg.get(category_for(row["stage"]), 0) + row["count"]
        return [{"category": k, "count": v}
                for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]
