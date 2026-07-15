"""Ledger — Phase 1 data-access layer (the source of truth).

Five tables: webhook_events, positions, paper_trades, bot_logs, alerts.

``SqliteLedger`` (default, dev/offline) and ``SupabaseLedger`` (prod, used when
``SUPABASE_URL`` + ``SUPABASE_KEY`` are set) implement the same ``Ledger``
interface, so the rest of the app is storage-agnostic. ``get_ledger()`` picks
one. Stdlib-only for SQLite; supabase-py is imported lazily only if configured.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

_SCHEMA = (Path(__file__).resolve().parent / "ledger_schema.sql").read_text(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


class Ledger(Protocol):
    # webhook events
    def insert_webhook_event(self, *, alert_id: str, symbol: str, side: str,
                             entry: Optional[float], stop: Optional[float],
                             payload: dict, status: str, reason: str = "") -> str: ...
    def webhook_seen(self, alert_id: str, since_iso: str) -> bool: ...
    def get_webhook_events(self, limit: int = 500) -> list[dict]: ...
    # positions / trades
    def open_position(self, *, symbol: str, side: str, size: float, entry: float,
                      stop: Optional[float]) -> str: ...
    def close_position(self, position_id: str, *, exit_price: float, pnl: float) -> None: ...
    def get_positions(self, status: Optional[str] = None) -> list[dict]: ...
    def record_paper_trade(self, trade: dict) -> str: ...
    def close_paper_trade(self, trade_id: str, *, exit_price: float, pnl: float, rr: float) -> None: ...
    def get_paper_trades(self) -> list[dict]: ...
    # logs / alerts
    def log(self, *, level: str, stage: str, message: str, symbol: str = "") -> None: ...
    def get_logs(self, limit: int = 200) -> list[dict]: ...
    def add_alert(self, *, severity: str, category: str, title: str, detail: str = "") -> None: ...
    def get_alerts(self, limit: int = 100) -> list[dict]: ...


class SqliteLedger:
    """Thread-safe SQLite ledger. A single connection is shared across the API
    request threads and the autonomous engine's background thread, so every
    access is guarded by a re-entrant lock."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._c.executescript(_SCHEMA)
            self._c.commit()

    # ----------------------------------------------------------- webhook
    def insert_webhook_event(self, *, alert_id, symbol, side, entry, stop, payload, status, reason=""):
        wid = _id()
        with self._lock:
            self._c.execute(
                "INSERT INTO webhook_events(id,alert_id,symbol,side,entry,stop,payload_json,received_at,status,reason)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (wid, alert_id, symbol, side, entry, stop, json.dumps(payload), _now(), status, reason))
            self._c.commit()
        return wid

    def webhook_seen(self, alert_id: str, since_iso: str) -> bool:
        with self._lock:
            r = self._c.execute(
                "SELECT 1 FROM webhook_events WHERE alert_id=? AND received_at>=? AND status!='rejected' LIMIT 1",
                (alert_id, since_iso)).fetchone()
        return r is not None

    def get_webhook_events(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._c.execute(
                "SELECT * FROM webhook_events ORDER BY received_at DESC LIMIT ?",
                (int(limit),)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.pop("payload_json") or "{}")
            except (TypeError, ValueError):
                d["payload"] = {}
            out.append(d)
        return out

    # ----------------------------------------------------------- positions
    def open_position(self, *, symbol, side, size, entry, stop):
        pid = _id()
        with self._lock:
            self._c.execute(
                "INSERT INTO positions(id,symbol,side,size,entry,stop,status,pnl,opened_at)"
                " VALUES (?,?,?,?,?,?, 'open', 0, ?)",
                (pid, symbol, side, size, entry, stop, _now()))
            self._c.commit()
        return pid

    def close_position(self, position_id, *, exit_price, pnl):
        with self._lock:
            self._c.execute("UPDATE positions SET status='closed', pnl=?, closed_at=? WHERE id=?",
                            (pnl, _now(), position_id))
            self._c.commit()

    def get_positions(self, status=None):
        q = "SELECT * FROM positions"
        args: tuple = ()
        if status:
            q += " WHERE status=?"
            args = (status,)
        q += " ORDER BY opened_at DESC"
        with self._lock:
            return [dict(r) for r in self._c.execute(q, args)]

    # ----------------------------------------------------------- paper trades
    def record_paper_trade(self, trade: dict) -> str:
        tid = trade.get("id") or _id()
        with self._lock:
            self._c.execute(
                "INSERT INTO paper_trades(id,alert_id,symbol,side,size,entry,stop,status,opened_at)"
                " VALUES (?,?,?,?,?,?,?, 'open', ?)",
                (tid, trade.get("alert_id"), trade["symbol"], trade["side"], trade["size"],
                 trade["entry"], trade.get("stop"), _now()))
            self._c.commit()
        return tid

    def close_paper_trade(self, trade_id, *, exit_price, pnl, rr):
        with self._lock:
            self._c.execute(
                "UPDATE paper_trades SET status='closed', exit=?, pnl=?, rr=?, closed_at=? WHERE id=?",
                (exit_price, pnl, rr, _now(), trade_id))
            self._c.commit()

    def get_paper_trades(self):
        with self._lock:
            return [dict(r) for r in self._c.execute("SELECT * FROM paper_trades ORDER BY opened_at DESC")]

    def reset_paper(self) -> None:
        """Clear paper trades + positions — used ONLY when the operator changes
        initial capital (a confirmed paper-account reset). Never live."""
        with self._lock:
            self._c.execute("DELETE FROM paper_trades")
            self._c.execute("DELETE FROM positions")
            self._c.commit()

    # ----------------------------------------------------------- logs / alerts
    def log(self, *, level, stage, message, symbol=""):
        with self._lock:
            self._c.execute(
                "INSERT INTO bot_logs(id,ts,symbol,level,stage,message) VALUES (?,?,?,?,?,?)",
                (_id(), _now(), symbol, level, stage, message))
            self._c.commit()

    def get_logs(self, limit=200):
        with self._lock:
            return [dict(r) for r in self._c.execute(
                "SELECT * FROM bot_logs ORDER BY ts DESC LIMIT ?", (limit,))]

    def add_alert(self, *, severity, category, title, detail=""):
        with self._lock:
            self._c.execute(
                "INSERT INTO alerts(id,ts,severity,category,title,detail,read) VALUES (?,?,?,?,?,?,0)",
                (_id(), _now(), severity, category, title, detail))
            self._c.commit()

    def get_alerts(self, limit=100):
        with self._lock:
            return [dict(r) for r in self._c.execute(
                "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,))]

    def prune(self, keep_logs=50000, keep_alerts=10000, keep_events=20000) -> dict:
        """Retention cap for the noisy append-only tables (bot_logs, alerts,
        webhook_events) — keep the most recent N of each, delete older. Trade
        rows (positions / paper_trades) are NEVER pruned; they are the record."""
        out = {}
        with self._lock:
            # id is a random string on these tables, so order by the real
            # timestamp column to keep the NEWEST rows (not a random subset).
            for table, tcol, keep, key in (("bot_logs", "ts", keep_logs, "logs"),
                                           ("alerts", "ts", keep_alerts, "alerts"),
                                           ("webhook_events", "received_at", keep_events, "events")):
                try:
                    cur = self._c.execute(
                        f"DELETE FROM {table} WHERE id NOT IN "
                        f"(SELECT id FROM {table} ORDER BY {tcol} DESC LIMIT ?)", (int(keep),))
                    out[key] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                except Exception:  # noqa: BLE001 — a table variant may differ
                    out[key] = 0
            self._c.commit()
        return out

    def close(self):
        with self._lock:
            self._c.close()


class SupabaseLedger:
    """Prod ledger backed by Supabase/Postgres (source of truth). Lazily imports
    supabase-py; only used when SUPABASE_URL + SUPABASE_KEY are set. Methods
    mirror SqliteLedger via the PostgREST table API."""

    def __init__(self, url: str, key: str):  # pragma: no cover - needs network + creds
        from supabase import create_client
        self._db = create_client(url, key)

    def _t(self, name):  # pragma: no cover
        return self._db.table(name)

    def insert_webhook_event(self, *, alert_id, symbol, side, entry, stop, payload, status, reason=""):  # pragma: no cover
        wid = _id()
        self._t("webhook_events").insert({
            "id": wid, "alert_id": alert_id, "symbol": symbol, "side": side,
            "entry": entry, "stop": stop, "payload_json": json.dumps(payload),
            "received_at": _now(), "status": status, "reason": reason,
        }).execute()
        return wid

    def webhook_seen(self, alert_id, since_iso):  # pragma: no cover
        res = self._t("webhook_events").select("id").eq("alert_id", alert_id)\
            .gte("received_at", since_iso).neq("status", "rejected").limit(1).execute()
        return bool(res.data)

    def get_webhook_events(self, limit=500):  # pragma: no cover
        rows = self._t("webhook_events").select("*").order("received_at", desc=True)\
            .limit(int(limit)).execute().data
        for d in rows:
            try:
                d["payload"] = json.loads(d.pop("payload_json") or "{}")
            except (TypeError, ValueError):
                d["payload"] = {}
        return rows

    def open_position(self, *, symbol, side, size, entry, stop):  # pragma: no cover
        pid = _id()
        self._t("positions").insert({
            "id": pid, "symbol": symbol, "side": side, "size": size, "entry": entry,
            "stop": stop, "status": "open", "pnl": 0, "opened_at": _now()}).execute()
        return pid

    def close_position(self, position_id, *, exit_price, pnl):  # pragma: no cover
        self._t("positions").update({"status": "closed", "pnl": pnl, "closed_at": _now()})\
            .eq("id", position_id).execute()

    def get_positions(self, status=None):  # pragma: no cover
        q = self._t("positions").select("*")
        if status:
            q = q.eq("status", status)
        return q.order("opened_at", desc=True).execute().data

    def record_paper_trade(self, trade):  # pragma: no cover
        tid = trade.get("id") or _id()
        self._t("paper_trades").insert({
            "id": tid, "alert_id": trade.get("alert_id"), "symbol": trade["symbol"],
            "side": trade["side"], "size": trade["size"], "entry": trade["entry"],
            "stop": trade.get("stop"), "status": "open", "opened_at": _now()}).execute()
        return tid

    def close_paper_trade(self, trade_id, *, exit_price, pnl, rr):  # pragma: no cover
        self._t("paper_trades").update({
            "status": "closed", "exit": exit_price, "pnl": pnl, "rr": rr,
            "closed_at": _now()}).eq("id", trade_id).execute()

    def get_paper_trades(self):  # pragma: no cover
        return self._t("paper_trades").select("*").order("opened_at", desc=True).execute().data

    def log(self, *, level, stage, message, symbol=""):  # pragma: no cover
        self._t("bot_logs").insert({"id": _id(), "ts": _now(), "symbol": symbol,
                                    "level": level, "stage": stage, "message": message}).execute()

    def get_logs(self, limit=200):  # pragma: no cover
        return self._t("bot_logs").select("*").order("ts", desc=True).limit(limit).execute().data

    def add_alert(self, *, severity, category, title, detail=""):  # pragma: no cover
        self._t("alerts").insert({"id": _id(), "ts": _now(), "severity": severity,
                                  "category": category, "title": title, "detail": detail,
                                  "read": 0}).execute()

    def get_alerts(self, limit=100):  # pragma: no cover
        return self._t("alerts").select("*").order("ts", desc=True).limit(limit).execute().data


# Honest Supabase health: get_ledger() records whether Supabase was configured
# and whether it actually ANSWERED, so the UI reports real persistence instead
# of trusting env vars alone — and a broken config never crashes the boot.
SUPABASE_STATUS: dict = {"configured": False, "connected": False, "error": None}


def get_ledger(sqlite_path: str = ":memory:") -> Ledger:
    """Supabase when configured AND reachable, else local SQLite.

    A misconfigured Supabase (bad URL/key, or the schema was never run) used to
    crash the app on boot — the startup event writes to the ledger — which made
    the whole deploy fail. Now we probe it once and fall back to SQLite with a
    loud log line instead; /paper/account surfaces the same error in the UI.
    """
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    SUPABASE_STATUS.update({"configured": bool(url and key),
                            "connected": False, "error": None})
    if url and key:
        try:
            led = SupabaseLedger(url, key)
            led.get_paper_trades()   # probe: fails fast on bad creds / missing schema
            SUPABASE_STATUS["connected"] = True
            return led
        except Exception as e:  # noqa: BLE001 — fall back, never crash the boot
            SUPABASE_STATUS["error"] = f"{type(e).__name__}: {e}"
            print(f"[ledger] Supabase configured but UNUSABLE — falling back to local "
                  f"SQLite. Error: {e}\n[ledger] Fix: run automation-hub/data/"
                  f"ledger_schema.sql in the Supabase SQL editor and verify "
                  f"SUPABASE_URL / SUPABASE_KEY (service_role), then redeploy.",
                  flush=True)
    return SqliteLedger(sqlite_path)
