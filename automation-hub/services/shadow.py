"""Shadow mode — audition a candidate strategy on live candles, risk-free.

Professional upgrade discipline: before any strategy change goes live, run the
candidate IN PARALLEL on the exact same bars the incumbent trades, with zero
capital. The shadow keeps its own virtual positions and R-multiples; the
report compares its record against the incumbent's live paper record and
gives a promotion verdict. Promotion itself stays HUMAN — the report tells
you when the evidence is there; you flip the strategy.

The tracker is deliberately simple and honest: entry at the signal bar's
close, pessimistic intrabar exits (stop before target), taker costs both
sides — a conservative floor for the candidate, not a flattering estimate.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

_COST_R_PER_SIDE = 0.0006     # fee + slippage per side, as fraction of price


class ShadowRun:
    """One candidate strategy shadowing the live engine's bars."""

    def __init__(self, name: str, factory, symbols: list[str]):
        self.name = name
        self.symbols = list(symbols)
        self._strats = {s: factory(s) for s in self.symbols}
        self._pos: dict[str, dict] = {}
        self.trades: list[dict] = []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- on_bar
    def on_bar(self, symbol: str, bar) -> None:
        strat = self._strats.get(symbol)
        if strat is None:
            return
        with self._lock:
            pos = self._pos.get(symbol)
            if pos is not None:
                exit_px = None
                if pos["side"] == "long":
                    if bar.low <= pos["stop"]:
                        exit_px = pos["stop"]
                    elif bar.high >= pos["target"]:
                        exit_px = pos["target"]
                else:
                    if bar.high >= pos["stop"]:
                        exit_px = pos["stop"]
                    elif bar.low <= pos["target"]:
                        exit_px = pos["target"]
                if exit_px is not None:
                    move = ((exit_px - pos["entry"]) if pos["side"] == "long"
                            else (pos["entry"] - exit_px))
                    cost_r = 2 * _COST_R_PER_SIDE * pos["entry"] / pos["risk"]
                    r = move / pos["risk"] - cost_r
                    self.trades.append({"symbol": symbol, "side": pos["side"],
                                        "entry": pos["entry"], "exit": exit_px,
                                        "r": round(r, 3),
                                        "time": bar.timestamp.isoformat()})
                    self._pos.pop(symbol, None)
        try:
            sig = strat.on_bar(bar)
        except Exception:  # noqa: BLE001 — a broken candidate must not affect live
            return
        if sig is None:
            return
        with self._lock:
            if symbol in self._pos:
                return
            entry, stop = sig.entry, sig.stop_loss
            if not stop or not entry or stop == entry:
                return
            from bot.types import SignalType
            self._pos[symbol] = {"side": "long" if sig.type == SignalType.LONG else "short",
                                 "entry": entry, "stop": stop,
                                 "target": sig.take_profit, "risk": abs(entry - stop)}

    # ----------------------------------------------------------------- stats
    def stats(self) -> dict:
        with self._lock:
            rs = [t["r"] for t in self.trades]
        n = len(rs)
        if n == 0:
            return {"trades": 0}
        wins = [r for r in rs if r > 0]
        return {"trades": n, "win_rate": round(100 * len(wins) / n, 1),
                "expectancy_r": round(sum(rs) / n, 3), "net_r": round(sum(rs), 2)}

    def report(self, live_stats: dict, min_trades: int = 20) -> dict:
        s = self.stats()
        verdict, detail = "collecting", ""
        if s.get("trades", 0) < min_trades or live_stats.get("trades", 0) < min_trades:
            detail = (f"Shadow {s.get('trades', 0)}/{min_trades} and live "
                      f"{live_stats.get('trades', 0)}/{min_trades} closed trades — "
                      f"not enough evidence yet.")
        elif s["expectancy_r"] > live_stats.get("expectancy_r", 0.0) + 0.1:
            verdict = "promote"
            detail = (f"Shadow expectancy {s['expectancy_r']:+.2f}R beats live "
                      f"{live_stats.get('expectancy_r', 0):+.2f}R by >0.1R over "
                      f"{s['trades']} trades — switching is justified.")
        elif s["expectancy_r"] < live_stats.get("expectancy_r", 0.0) - 0.1:
            verdict = "reject"
            detail = "Shadow underperforms the incumbent — keep the current strategy."
        else:
            verdict = "tie"
            detail = "No material difference yet — keep collecting."
        return {"candidate": self.name, "started_at": self.started_at,
                "shadow": s, "live": live_stats,
                "open_virtual_positions": len(self._pos),
                "verdict": verdict, "detail": detail,
                "note": "Shadow fills are conservative (taker costs both sides)."}


def live_stats_from_history(history: list[dict], since_iso: Optional[str] = None) -> dict:
    """Incumbent stats from closed paper trades, optionally only those closed
    after the shadow started (fair same-period comparison)."""
    rs = []
    for t in history:
        if t.get("status", "closed") != "closed" or t.get("rr") is None:
            continue
        if since_iso and (t.get("closed_at") or "") < since_iso:
            continue
        rs.append(float(t["rr"]))
    n = len(rs)
    if n == 0:
        return {"trades": 0}
    wins = [r for r in rs if r > 0]
    return {"trades": n, "win_rate": round(100 * len(wins) / n, 1),
            "expectancy_r": round(sum(rs) / n, 3), "net_r": round(sum(rs), 2)}
