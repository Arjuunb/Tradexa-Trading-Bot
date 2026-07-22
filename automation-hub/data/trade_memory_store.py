"""Permanent trade-memory store — the AI's long-term memory of every trade.

One row per closed trade, composed from REAL captured data (the decision
journal, the decision object, the ledger). Nothing here is invented: fields
the bot never measured are stored as honest markers ("not captured" /
"Not checked"), never as fabricated numbers.

Design goals from the spec:
  * "Remember every trade forever unless deleted" — rows persist under
    HUB_DATA_DIR (SQLite) and are only removed by an explicit delete().
  * Natural-language / semantic search — an FTS5 full-text index over the
    human-readable memory (reasons, mistakes, lessons, reflection, notes)
    plus a numeric feature vector per trade for similarity ("find trades
    like this one"). This is honest local search, NOT an LLM embedding
    model; the interface leaves room to plug one in later.
  * Nightly/weekly/monthly/yearly pattern reviews are persisted too.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from data.tenant_scope import ensure_tenant_column


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Columns persisted verbatim on the memory row (summary + denormalised facets
# used for filtering). The full 8-category record lives in sections_json.
_COLS = (
    "trade_id", "created_at", "closed_at", "mode", "symbol", "side", "strategy",
    "timeframe", "entry", "exit", "stop", "target", "size", "risk_amount",
    "planned_rr", "actual_rr", "pnl", "result", "grade", "confidence",
    "brain_score", "regime", "session", "weekday", "duration_s",
    "sections_json", "features_json", "notes", "updated_at",
)


class TradeMemoryStore:
    """Durable, append-mostly memory of every trade. Thread-safe."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._fts = False
        with self._lock:
            self._c.executescript(
                """
                CREATE TABLE IF NOT EXISTS trade_memories (
                    trade_id     TEXT PRIMARY KEY,
                    created_at   TEXT,
                    closed_at    TEXT,
                    mode         TEXT,
                    symbol       TEXT,
                    side         TEXT,
                    strategy     TEXT,
                    timeframe    TEXT,
                    entry        REAL,
                    exit         REAL,
                    stop         REAL,
                    target       REAL,
                    size         REAL,
                    risk_amount  REAL,
                    planned_rr   REAL,
                    actual_rr    REAL,
                    pnl          REAL,
                    result       TEXT,
                    grade        TEXT,
                    confidence   REAL,
                    brain_score  REAL,
                    regime       TEXT,
                    session      TEXT,
                    weekday      TEXT,
                    duration_s   REAL,
                    sections_json TEXT,
                    features_json TEXT,
                    notes        TEXT,
                    updated_at   TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_mem_symbol  ON trade_memories(symbol);
                CREATE INDEX IF NOT EXISTS ix_mem_result  ON trade_memories(result);
                CREATE INDEX IF NOT EXISTS ix_mem_session ON trade_memories(session);
                CREATE INDEX IF NOT EXISTS ix_mem_closed  ON trade_memories(closed_at);

                CREATE TABLE IF NOT EXISTS memory_reviews (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    period      TEXT NOT NULL,       -- nightly | weekly | monthly | yearly
                    period_key  TEXT NOT NULL,       -- e.g. 2026-07-12 / 2026-W28 / 2026-07 / 2026
                    created_at  TEXT,
                    report_json TEXT,
                    UNIQUE(period, period_key)
                );
                """)
            for _t in ("trade_memories", "memory_reviews"):   # Phase C-3: schema-only, additive
                ensure_tenant_column(self._c, _t)
            self._c.commit()
            # FTS5 is optional at runtime; degrade to LIKE search if absent.
            try:
                self._c.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS trade_memories_fts "
                    "USING fts5(trade_id UNINDEXED, body)")
                self._c.commit()
                self._fts = True
            except sqlite3.OperationalError:
                self._fts = False

    # ------------------------------------------------------------------ write
    def upsert(self, mem: dict) -> None:
        """Insert or replace the full memory row. ``mem`` carries the summary
        fields, a ``sections`` dict (the 8 categories), a ``features`` dict
        (numeric vector) and optional ``notes``. FTS body is rebuilt each time
        so notes/reflection edits are searchable immediately."""
        row = {k: mem.get(k) for k in _COLS}
        row["trade_id"] = mem["trade_id"]
        row["sections_json"] = json.dumps(mem.get("sections", {}))
        row["features_json"] = json.dumps(mem.get("features", {}))
        row["notes"] = mem.get("notes") or ""
        row["updated_at"] = _now()
        cols = ", ".join(_COLS)
        placeholders = ", ".join("?" for _ in _COLS)
        with self._lock:
            self._c.execute(
                f"INSERT OR REPLACE INTO trade_memories ({cols}) VALUES ({placeholders})",
                tuple(row[k] for k in _COLS))
            self._reindex(row["trade_id"], mem)
            self._c.commit()

    def set_notes(self, trade_id: str, notes: str) -> bool:
        """Attach the trader's manual journal note (e.g. 'FOMO', 'entered early')."""
        with self._lock:
            r = self._c.execute("SELECT sections_json FROM trade_memories WHERE trade_id=?",
                                (trade_id,)).fetchone()
            if r is None:
                return False
            sections = json.loads(r["sections_json"] or "{}")
            emo = sections.setdefault("emotion_journal", {})
            emo["manual_notes"] = notes
            self._c.execute(
                "UPDATE trade_memories SET notes=?, sections_json=?, updated_at=? WHERE trade_id=?",
                (notes or "", json.dumps(sections), _now(), trade_id))
            self._reindex(trade_id, {"notes": notes, "sections": sections})
            self._c.commit()
            return True

    def delete(self, trade_id: str) -> bool:
        """Permanently forget one trade. The ONLY way a memory leaves the store —
        everything else is remembered forever."""
        with self._lock:
            cur = self._c.execute("DELETE FROM trade_memories WHERE trade_id=?", (trade_id,))
            if self._fts:
                self._c.execute("DELETE FROM trade_memories_fts WHERE trade_id=?", (trade_id,))
            self._c.commit()
            return cur.rowcount > 0

    def _reindex(self, trade_id: str, mem: dict) -> None:
        if not self._fts:
            return
        self._c.execute("DELETE FROM trade_memories_fts WHERE trade_id=?", (trade_id,))
        self._c.execute(
            "INSERT INTO trade_memories_fts (trade_id, body) VALUES (?, ?)",
            (trade_id, _search_body(mem)))

    # ------------------------------------------------------------------- read
    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["sections"] = json.loads(d.pop("sections_json") or "{}")
        d["features"] = json.loads(d.pop("features_json") or "{}")
        return d

    def get(self, trade_id: str) -> Optional[dict]:
        with self._lock:
            r = self._c.execute("SELECT * FROM trade_memories WHERE trade_id=?",
                                (trade_id,)).fetchone()
            return self._row(r) if r else None

    def list(self, *, limit: int = 200, q: Optional[str] = None,
             symbol: Optional[str] = None, result: Optional[str] = None,
             strategy: Optional[str] = None, session: Optional[str] = None) -> list[dict]:
        """List memories, newest first. ``q`` runs a full-text search over the
        human-readable memory; the other args are exact facet filters."""
        args: list = []
        if q and self._fts:
            base = ("SELECT m.* FROM trade_memories m "
                    "JOIN trade_memories_fts f ON f.trade_id = m.trade_id "
                    "WHERE trade_memories_fts MATCH ?")
            args.append(_fts_query(q))
        elif q:
            base = "SELECT * FROM trade_memories m WHERE (notes LIKE ? OR sections_json LIKE ?)"
            like = f"%{q}%"; args += [like, like]
        else:
            base = "SELECT * FROM trade_memories m WHERE 1=1"
        if symbol:
            base += " AND m.symbol=?"; args.append(symbol.upper())
        if result:
            base += " AND m.result=?"; args.append(result)
        if strategy:
            base += " AND m.strategy=?"; args.append(strategy)
        if session:
            base += " AND m.session=?"; args.append(session)
        base += " ORDER BY m.closed_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            return [self._row(r) for r in self._c.execute(base, args)]

    def all_features(self) -> list[dict]:
        """Every memory's feature vector — the raw material for similarity."""
        with self._lock:
            rows = self._c.execute(
                "SELECT trade_id, symbol, side, result, features_json FROM trade_memories").fetchall()
        out = []
        for r in rows:
            out.append({"trade_id": r["trade_id"], "symbol": r["symbol"],
                        "side": r["side"], "result": r["result"],
                        "features": json.loads(r["features_json"] or "{}")})
        return out

    def count(self) -> int:
        with self._lock:
            return int(self._c.execute("SELECT COUNT(*) c FROM trade_memories").fetchone()["c"])

    def existing_ids(self) -> set:
        with self._lock:
            return {r["trade_id"] for r in
                    self._c.execute("SELECT trade_id FROM trade_memories")}

    # ---------------------------------------------------------------- reviews
    def save_review(self, period: str, period_key: str, report: dict) -> None:
        with self._lock:
            self._c.execute(
                """INSERT INTO memory_reviews (period, period_key, created_at, report_json)
                   VALUES (?,?,?,?)
                   ON CONFLICT(period, period_key)
                   DO UPDATE SET created_at=excluded.created_at, report_json=excluded.report_json""",
                (period, period_key, _now(), json.dumps(report)))
            self._c.commit()

    def get_reviews(self, period: Optional[str] = None, limit: int = 12) -> list[dict]:
        with self._lock:
            if period:
                rows = self._c.execute(
                    "SELECT * FROM memory_reviews WHERE period=? ORDER BY period_key DESC LIMIT ?",
                    (period, int(limit))).fetchall()
            else:
                rows = self._c.execute(
                    "SELECT * FROM memory_reviews ORDER BY created_at DESC LIMIT ?",
                    (int(limit),)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["report"] = json.loads(d.pop("report_json") or "{}")
            out.append(d)
        return out


# --------------------------------------------------------------------- helpers
def _search_body(mem: dict) -> str:
    """Flatten the human-readable memory into one searchable text blob."""
    parts: list[str] = []
    for k in ("symbol", "side", "strategy", "regime", "session", "weekday", "result", "grade"):
        v = mem.get(k)
        if v:
            parts.append(str(v))
    if mem.get("notes"):
        parts.append(str(mem["notes"]))
    s = mem.get("sections", {}) or {}
    for cat in s.values():
        _collect_text(cat, parts)
    return " ".join(parts)


def _collect_text(obj, out: list, depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_text(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_text(v, out, depth + 1)


def _fts_query(q: str) -> str:
    """Turn a free-text query into a safe FTS5 MATCH expression: OR the tokens
    so 'losing BTC trades' matches rows containing any of those words. Quoting
    each token neutralises FTS operator characters."""
    toks = [t for t in ''.join(c if (c.isalnum() or c.isspace()) else ' '
                               for c in q).split() if t]
    if not toks:
        return '""'
    return " OR ".join(f'"{t}"' for t in toks)
