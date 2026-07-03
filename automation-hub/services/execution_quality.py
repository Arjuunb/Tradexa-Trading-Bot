"""Execution quality — measure every fill against its intent.

Professional desks grade their own execution: every fill records the intended
price vs the actual fill, signed so positive slippage = money lost to
execution. The report splits maker vs taker and compares the measured taker
slippage against what the fill model ASSUMES — if reality is worse than the
model, backtests are too optimistic and the model needs recalibrating.

Pure in-memory rolling window (no I/O on the trade path).
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone


def slippage_bps(side: str, intended: float, filled: float) -> float:
    """Signed slippage in basis points; positive = fill worse than intended.
    ``side`` is the executed direction: 'buy' pays up, 'sell' receives less."""
    if intended <= 0:
        return 0.0
    raw = (filled - intended) / intended if side == "buy" else (intended - filled) / intended
    return round(raw * 10_000, 3)


class ExecutionQuality:
    def __init__(self, max_records: int = 1000):
        self._records: deque = deque(maxlen=max_records)
        self._lock = threading.Lock()

    def record(self, *, symbol: str, side: str, intended: float, filled: float,
               kind: str = "entry", maker: bool = False) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
               "side": side, "kind": kind, "maker": maker,
               "intended": intended, "filled": filled,
               "slippage_bps": slippage_bps(side, intended, filled)}
        with self._lock:
            self._records.append(rec)

    @staticmethod
    def _agg(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"fills": 0}
        s = sorted(r["slippage_bps"] for r in rows)
        return {"fills": n, "avg_bps": round(sum(s) / n, 2),
                "median_bps": round(s[n // 2], 2), "worst_bps": round(s[-1], 2),
                "best_bps": round(s[0], 2)}

    def report(self, fill_model=None) -> dict:
        with self._lock:
            rows = list(self._records)
        makers = [r for r in rows if r["maker"]]
        takers = [r for r in rows if not r["maker"]]
        by_symbol = {}
        for r in rows:
            by_symbol.setdefault(r["symbol"], []).append(r)
        out = {"overall": self._agg(rows), "maker": self._agg(makers),
               "taker": self._agg(takers),
               "by_symbol": {s: self._agg(v) for s, v in by_symbol.items()},
               "recent": rows[-20:]}
        # calibration: measured taker slippage vs what the model assumes
        if fill_model is not None and takers:
            assumed = round(getattr(fill_model, "cost_pct", 0.0) * 10_000, 2)
            measured = out["taker"]["avg_bps"]
            out["model_calibration"] = {
                "model": getattr(fill_model, "name", "?"),
                "assumed_bps": assumed, "measured_bps": measured,
                "verdict": ("model optimistic — backtests overstate results; raise the "
                            "model's slippage" if measured > assumed * 1.5 + 0.5 else
                            "model conservative" if measured < assumed * 0.5 else
                            "model consistent with measured fills"),
            }
        return out
