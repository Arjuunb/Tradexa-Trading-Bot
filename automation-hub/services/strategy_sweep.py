"""Multi-asset / multi-timeframe sweep — makes "best asset" and "best timeframe"
answerable instead of declared un-answerable.

A single backtest runs one symbol on one timeframe, so those two questions
genuinely cannot be answered from it. Running the SAME spec across a set of
symbols and timeframes can answer them — and this does exactly that, using the
same simulate path as everything else. No new engine, no extrapolation: each
cell is a real backtest.

Combinations are capped and every skipped cell is reported with its reason, so a
partial sweep is never presented as a complete one.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

MAX_CELLS = 24          # keeps a sweep bounded; the caller is told when it bites
_MIN_TRADES = 5         # a cell below this is ranked but flagged as thin


def sweep(spec: dict, symbols: list[str], timeframes: list[str],
          runner: Callable[[dict, str, str], Optional[dict]],
          *, max_cells: int = MAX_CELLS) -> dict:
    """Run ``spec`` over every symbol x timeframe cell.

    ``runner(spec, symbol, timeframe) -> results | None`` does the actual
    backtest (injected so this module stays pure and testable).
    """
    symbols = [s for s in dict.fromkeys(symbols or []) if s]
    timeframes = [t for t in dict.fromkeys(timeframes or []) if t]
    if not symbols:
        symbols = [spec.get("symbol", "BTCUSDT")]
    if not timeframes:
        timeframes = [spec.get("timeframe", "4h")]

    cells: list[dict] = []
    skipped: list[dict] = []
    truncated = False

    for sym in symbols:
        for tf in timeframes:
            if len(cells) + len(skipped) >= max_cells:
                truncated = True
                break
            try:
                res = runner(spec, sym, tf)
            except Exception as e:  # noqa: BLE001 — one bad cell must not kill the sweep
                skipped.append({"symbol": sym, "timeframe": tf,
                                "why": f"backtest failed ({type(e).__name__})"})
                continue
            if not res or not res.get("trades"):
                skipped.append({"symbol": sym, "timeframe": tf,
                                "why": "no trades / no market data for this combination"})
                continue
            cells.append({
                "symbol": sym, "timeframe": tf,
                # True when the data really came back at the requested spacing.
                # Some sources return one fixed granularity regardless of the
                # timeframe asked for; ranking timeframes on that would compare
                # identical data and report a meaningless winner.
                "tf_verified": bool(res.get("__tf_verified", True)),
                "trades": res.get("total_trades"),
                "net_r": res.get("net_r"), "net_pct": res.get("net_pct"),
                "win_rate": res.get("win_rate"),
                "profit_factor": res.get("profit_factor"),
                "max_drawdown_r": res.get("max_drawdown_r"),
                "expectancy_r": res.get("expectancy_r"),
                "thin": (res.get("total_trades") or 0) < _MIN_TRADES,
            })
        if truncated:
            break

    ranked = sorted(cells, key=lambda c: (c.get("net_r") or 0), reverse=True)
    solid = [c for c in ranked if not c["thin"]]
    # Timeframe ranking is only meaningful across cells whose data really came
    # back at the requested spacing.
    tf_ok = [c for c in solid if c["tf_verified"]]
    tf_unverified = sorted({c["symbol"] for c in cells if not c["tf_verified"]})

    caveats = []
    if tf_unverified:
        caveats.append(
            "Timeframe comparison excludes " + ", ".join(tf_unverified) +
            " — that data source returns one fixed candle size regardless of the "
            "timeframe requested, so its timeframes are not actually different.")

    return {
        "available": bool(cells),
        "cells": ranked,
        "skipped": skipped,
        "truncated": truncated,
        "max_cells": max_cells,
        "best_asset": _best_by(solid, "symbol"),
        "worst_asset": _worst_by(solid, "symbol"),
        "best_timeframe": _best_by(tf_ok, "timeframe"),
        "worst_timeframe": _worst_by(tf_ok, "timeframe"),
        "timeframe_comparable": bool(tf_ok),
        "caveats": caveats,
        "note": None if cells else
                "No combination produced trades — nothing can be ranked.",
    }


def _agg(cells: list[dict], key: str) -> list[dict]:
    """Aggregate net R per distinct value of ``key`` (a symbol or a timeframe)."""
    groups: dict[str, list[dict]] = {}
    for c in cells:
        groups.setdefault(str(c[key]), []).append(c)
    out = []
    for k, rows in groups.items():
        nets = [r.get("net_r") or 0 for r in rows]
        out.append({key: k, "net_r": round(sum(nets), 2), "cells": len(rows),
                    "trades": sum(r.get("trades") or 0 for r in rows)})
    return sorted(out, key=lambda d: d["net_r"], reverse=True)


def _best_by(cells: list[dict], key: str) -> Optional[dict]:
    rows = _agg(cells, key)
    return rows[0] if rows else None


def _worst_by(cells: list[dict], key: str) -> Optional[dict]:
    rows = _agg(cells, key)
    # only meaningful with something to compare against
    return rows[-1] if len(rows) > 1 else None


_TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60,
           "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440, "1w": 10080}


def timeframe_matches(rows, timeframe: str) -> bool:
    """Did the data actually come back at the requested candle size?

    Some sources (e.g. the bundled sample series) return one fixed granularity
    whatever timeframe is asked for. Comparing timeframes on that data would be
    comparing a series against itself, so the sweep needs to know."""
    want = _TF_MIN.get(str(timeframe).lower())
    if not want or len(rows) < 3:
        return True                       # unknown / too short to judge — don't cry wolf
    deltas = []
    for a, b in zip(rows[:6], rows[1:7]):
        try:
            deltas.append(abs((b.timestamp - a.timestamp).total_seconds()) / 60.0)
        except Exception:  # noqa: BLE001 — a malformed timestamp is not proof of mismatch
            return True
    if not deltas:
        return True
    actual = min(d for d in deltas if d > 0) if any(d > 0 for d in deltas) else 0
    return abs(actual - want) <= max(1.0, want * 0.1)


def make_runner(bars_for_range, range_key: str) -> Callable[[dict, str, str], Any]:
    """Default runner: the shared spec runner, with the timeframe-integrity check
    wired in so a feed that ignores the requested candle size cannot produce a
    fabricated "best timeframe"."""
    from services.spec_runner import make_cell_runner
    return make_cell_runner(bars_for_range, range_key,
                            verify_timeframe=timeframe_matches)
