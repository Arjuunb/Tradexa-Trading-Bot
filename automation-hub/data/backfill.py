"""Deep historical backfill — years of REAL candles, run as a background job.

A professional bot is validated on years of real market data, not weeks. This
module turns the existing pager into a bulk backfill (``years`` instead of a
candle count) and runs the whole symbol×timeframe matrix on a background
thread with live progress — kick it once on the deployed host, watch
/data/backfill/status, then validate with /research/validate-real.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from data.historical import SYMBOLS, HistoricalStore, fetch_klines, sync

# closed candles per year, per timeframe
_BARS_PER_YEAR = {"5m": 105_120, "15m": 35_040, "30m": 17_520, "1h": 8_760,
                  "4h": 2_190, "1d": 365, "1w": 52}
DEFAULT_TIMEFRAMES = ("1h", "4h", "1d")


def deep_backfill(store: HistoricalStore, symbol: str, timeframe: str, *,
                  years: float = 3.0, candles: int = 0,
                  fetcher: Callable = fetch_klines, progress: Callable = None) -> dict:
    """Backfill one symbol/timeframe: ``candles`` (flat count, the quick-load
    mode) when given, else ``years`` worth for that timeframe (the deep mode)."""
    if candles:
        target = int(candles)
    else:
        per_year = _BARS_PER_YEAR.get(timeframe)
        if per_year is None:
            return {"error": f"unsupported timeframe {timeframe}"}
        target = int(per_year * max(0.1, float(years)))
    return sync(store, symbol, timeframe, target_candles=target, fetcher=fetcher,
                progress=progress)


class BackfillJob:
    """One background deep-backfill across symbols × timeframes, with progress."""

    def __init__(self, store: HistoricalStore):
        self.store = store
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.state: dict = {"running": False, "started_at": None, "finished_at": None,
                            "done": 0, "total": 0, "current": None, "results": []}

    def start(self, *, symbols=SYMBOLS, timeframes=DEFAULT_TIMEFRAMES,
              years: float = 3.0, candles: int = 0,
              fetcher: Callable = fetch_klines) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"started": False, "reason": "backfill already running",
                        **self.state}
            # quick wins first: big timeframes finish in one page, so the
            # progress counter moves within seconds instead of looking frozen
            order = {tf: i for i, tf in enumerate(("1w", "1d", "4h", "1h", "30m", "15m", "5m"))}
            tfs = sorted(timeframes, key=lambda t: order.get(t, 99))
            pairs = [(s, tf) for tf in tfs for s in symbols]
            self.state = {"running": True, "years": years, "candles": candles,
                          "started_at": datetime.now(timezone.utc).isoformat(),
                          "finished_at": None, "done": 0, "total": len(pairs),
                          "current": None, "current_candles": None, "results": []}
            self._thread = threading.Thread(
                target=self._run, args=(pairs, years, candles, fetcher),
                name="backfill", daemon=True)
            self._thread.start()
        return {"started": True, **self.state}

    def _run(self, pairs, years: float, candles: int, fetcher: Callable) -> None:
        def _progress(got: int, target: int) -> None:
            self.state["current_candles"] = f"{got:,}/{target:,} candles"

        for sym, tf in pairs:
            self.state["current"] = f"{sym} {tf}"
            self.state["current_candles"] = None
            t0 = time.time()
            try:
                res = deep_backfill(self.store, sym, tf, years=years, candles=candles,
                                    fetcher=fetcher, progress=_progress)
            except Exception as e:  # noqa: BLE001 — record and move on
                res = {"symbol": sym, "timeframe": tf, "error": str(e)}
            res["seconds"] = round(time.time() - t0, 1)
            self.state["results"].append(res)
            self.state["done"] += 1
        self.state["running"] = False
        self.state["current"] = None
        self.state["current_candles"] = None
        self.state["finished_at"] = datetime.now(timezone.utc).isoformat()

    def status(self) -> dict:
        ok = sum(1 for r in self.state["results"] if "error" not in r)
        errs = [r for r in self.state["results"] if "error" in r]
        return {**self.state, "succeeded": ok, "failed": len(errs)}
