"""Decision-journal storage — the full, explainable record of every bot trade.

Three tables (linked to the ledger's paper_trades by trade_id):
    trade_decision_journal  one row per trade: summary + the rich decision
                            sections (entry reasoning, rule checklist, market
                            snapshot, risk check, exit, review, evolution) as
                            JSON, so every trade is explainable and searchable.
    trade_decision_events   the trade timeline — one row per event.
    evolution_memory        aggregated learning per setup (strategy·regime·side)
                            with the early-signal / evidence staging the bot
                            uses to decide how much a pattern can be trusted.

Everything stored here is REAL decision data captured at the moment it was
produced. Nothing is fabricated: a field the bot did not compute is stored as
"Not checked", never invented.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

EARLY_SIGNAL_MAX = 30       # < this many trades for a setup = early signal only
EVIDENCE_MIN = 50           # >= this = strong enough for stronger changes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JournalStore:
    def __init__(self, path: str = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._c.executescript("""
            CREATE TABLE IF NOT EXISTS trade_decision_journal (
                trade_id TEXT PRIMARY KEY, created_at TEXT, closed_at TEXT,
                mode TEXT, symbol TEXT, side TEXT, strategy TEXT, timeframe TEXT,
                entry REAL, stop REAL, target REAL, exit REAL, size REAL,
                risk_amount REAL, planned_rr REAL, actual_rr REAL, pnl REAL,
                result TEXT, confidence REAL, brain_score REAL, regime TEXT,
                grade TEXT, status TEXT, sections_json TEXT);
            CREATE TABLE IF NOT EXISTS trade_decision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT, ts TEXT,
                kind TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS evolution_memory (
                setup_key TEXT PRIMARY KEY, strategy TEXT, regime TEXT, side TEXT,
                trades INTEGER, wins INTEGER, net_r REAL, updated_at TEXT,
                stage TEXT, note TEXT);
            CREATE INDEX IF NOT EXISTS idx_evt_trade ON trade_decision_events(trade_id);
            """)
            self._c.commit()

    # ------------------------------------------------------------- entry
    def record_entry(self, j: dict) -> None:
        """Insert the journal at trade open. ``j`` carries the summary fields +
        a ``sections`` dict (entry_decision / checklist / market_snapshot /
        risk_check)."""
        with self._lock:
            self._c.execute(
                """INSERT OR REPLACE INTO trade_decision_journal
                (trade_id, created_at, mode, symbol, side, strategy, timeframe,
                 entry, stop, target, size, risk_amount, planned_rr, confidence,
                 brain_score, regime, status, sections_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?)""",
                (j["trade_id"], _now(), j.get("mode", "paper"), j.get("symbol"),
                 j.get("side"), j.get("strategy"), j.get("timeframe"), j.get("entry"),
                 j.get("stop"), j.get("target"), j.get("size"), j.get("risk_amount"),
                 j.get("planned_rr"), j.get("confidence"), j.get("brain_score"),
                 j.get("regime"), json.dumps(j.get("sections", {}))))
            self._c.commit()

    def add_event(self, trade_id: str, kind: str, detail: str = "",
                  ts: Optional[str] = None) -> None:
        with self._lock:
            self._c.execute(
                "INSERT INTO trade_decision_events(trade_id, ts, kind, detail) VALUES (?,?,?,?)",
                (trade_id, ts or _now(), kind, detail))
            self._c.commit()

    # ------------------------------------------------------------- close
    def close_trade(self, trade_id: str, *, exit: float, pnl: float, actual_rr: float,
                    result: str, grade: str, extra_sections: dict) -> None:
        with self._lock:
            row = self._c.execute(
                "SELECT sections_json FROM trade_decision_journal WHERE trade_id=?",
                (trade_id,)).fetchone()
            if row is None:
                return
            sections = json.loads(row["sections_json"] or "{}")
            sections.update(extra_sections)          # exit_decision / review / evolution
            self._c.execute(
                """UPDATE trade_decision_journal SET closed_at=?, exit=?, pnl=?,
                   actual_rr=?, result=?, grade=?, status='closed', sections_json=?
                   WHERE trade_id=?""",
                (_now(), exit, pnl, actual_rr, result, grade,
                 json.dumps(sections), trade_id))
            self._c.commit()

    # ------------------------------------------------------------- queries
    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["sections"] = json.loads(d.pop("sections_json") or "{}")
        return d

    def get(self, trade_id: str) -> Optional[dict]:
        with self._lock:
            r = self._c.execute("SELECT * FROM trade_decision_journal WHERE trade_id=?",
                                (trade_id,)).fetchone()
            if r is None:
                return None
            j = self._row(r)
            j["events"] = [dict(e) for e in self._c.execute(
                "SELECT ts, kind, detail FROM trade_decision_events WHERE trade_id=? ORDER BY id",
                (trade_id,))]
            return j

    def list(self, limit: int = 100, mode: Optional[str] = None,
             symbol: Optional[str] = None, result: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM trade_decision_journal"
        cond, args = [], []
        if mode:
            cond.append("mode=?"); args.append(mode)
        if symbol:
            cond.append("symbol=?"); args.append(symbol.upper())
        if result:
            cond.append("result=?"); args.append(result)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            return [self._row(r) for r in self._c.execute(q, args)]

    # ------------------------------------------------------------- evolution
    def update_evolution(self, setup_key: str, strategy: str, regime: str,
                         side: str, r: float) -> dict:
        """Fold one closed trade into the setup's aggregated memory + restage."""
        with self._lock:
            row = self._c.execute("SELECT * FROM evolution_memory WHERE setup_key=?",
                                  (setup_key,)).fetchone()
            trades = (row["trades"] if row else 0) + 1
            wins = (row["wins"] if row else 0) + (1 if r > 0 else 0)
            net_r = (row["net_r"] if row else 0.0) + r
            stage = ("evidence" if trades >= EVIDENCE_MIN
                     else "building" if trades >= EARLY_SIGNAL_MAX else "early-signal")
            wr = round(100 * wins / trades, 1)
            note = (f"{trades} trades, {wr}% win, {net_r:+.1f}R net. "
                    + ("Strong enough to inform strategy changes." if stage == "evidence"
                       else "Early signal — do NOT change strategy on this alone."
                       if stage == "early-signal" else
                       "Building evidence — keep observing before changes."))
            self._c.execute(
                """INSERT OR REPLACE INTO evolution_memory
                (setup_key, strategy, regime, side, trades, wins, net_r, updated_at, stage, note)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (setup_key, strategy, regime, side, trades, wins, net_r, _now(), stage, note))
            self._c.commit()
            return {"setup_key": setup_key, "trades": trades, "win_rate": wr,
                    "net_r": round(net_r, 2), "stage": stage, "note": note}

    def evolution(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._c.execute(
                "SELECT * FROM evolution_memory ORDER BY trades DESC")]
