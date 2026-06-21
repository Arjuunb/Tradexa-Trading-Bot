"""Trade Journal (#11).

Every closed trade auto-creates a journal entry with a chart snapshot reference
(symbol / timeframe / entry+exit bar — the UI can replay it), auto-written notes,
and seeded mistakes + lessons drawn from the trade's own diagnosis. The human
fields (notes / emotions) stay editable.

We store a *snapshot reference* the replay can reconstruct, not a fabricated PNG.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def auto_entry(trade: dict, *, symbol: str, strategy: str, timeframe: str) -> dict:
    """Seed a journal entry from a replay/paper trade."""
    side = trade.get("side", "")
    rr = trade.get("rr", trade.get("r"))
    result = trade.get("result") or ("Winner" if (rr or 0) > 0 else "Loser" if (rr or 0) < 0 else "Break Even")
    reasons = trade.get("entry_reasons") or []
    loss = trade.get("loss_analysis")
    notes = (f"{side.title()} {symbol} — " + (", ".join(reasons[:2]) or "setup met")
             + f". {result}" + (f" ({rr:+.2f}R)" if rr is not None else "") + ".")
    mistakes, lessons = [], []
    if loss:
        mistakes.append(loss)
        low = loss.lower()
        if "choppy" in low or "ranging" in low:
            lessons.append("Skip entries in choppy / ranging conditions.")
        elif "early" in low or "false breakout" in low:
            lessons.append("Wait for a confirmation candle / retest before entering.")
        elif "higher-timeframe" in low:
            lessons.append("Only trade with the higher-timeframe trend.")
        else:
            lessons.append("Review the stop placement and entry timing for this setup.")
    elif (rr or 0) > 0:
        lessons.append("Repeatable setup — note the confluence that worked.")
    return {
        "id": uuid.uuid4().hex, "trade_id": trade.get("id"),
        "symbol": symbol, "strategy": strategy, "timeframe": timeframe,
        "side": side, "result": result, "rr": rr,
        "entry": trade.get("entry"), "exit": trade.get("exit"),
        "snapshot": {"symbol": symbol, "timeframe": timeframe,
                     "entry_idx": trade.get("entry_idx"), "exit_idx": trade.get("exit_idx")},
        "notes": notes, "emotions": "", "mistakes": mistakes, "lessons": lessons,
        "tags": [strategy, result], "created_at": _now(), "auto": True,
    }


class JournalStore:
    def __init__(self, path: str):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def list(self) -> list:
        return sorted(self._load().values(), key=lambda e: e.get("created_at", ""), reverse=True)

    def add(self, entry: dict) -> dict:
        data = self._load()
        data[entry["id"]] = entry
        self._write(data)
        return entry

    def add_from_trades(self, trades: list, *, symbol: str, strategy: str, timeframe: str,
                        dedupe: bool = True) -> list:
        """Auto-journal a batch of closed trades; skips ones already journaled."""
        data = self._load()
        seen = {(e.get("strategy"), e.get("symbol"), e.get("trade_id")) for e in data.values()} if dedupe else set()
        added = []
        for t in trades:
            if t.get("rr") is None and t.get("r") is None:
                continue
            key = (strategy, symbol, t.get("id"))
            if dedupe and key in seen:
                continue
            e = auto_entry(t, symbol=symbol, strategy=strategy, timeframe=timeframe)
            data[e["id"]] = e
            added.append(e)
            seen.add(key)
        self._write(data)
        return added

    def update(self, eid: str, fields: dict) -> dict | None:
        data = self._load()
        if eid not in data:
            return None
        for k in ("notes", "emotions", "mistakes", "lessons", "tags"):
            if k in fields and fields[k] is not None:
                data[eid][k] = fields[k]
        data[eid]["updated_at"] = _now()
        self._write(data)
        return data[eid]

    def delete(self, eid: str) -> bool:
        data = self._load()
        if eid in data:
            del data[eid]
            self._write(data)
            return True
        return False
