"""Data integrity — a backtest is only as honest as its candles.

Verifies a cached candle series: gaps (missing intervals), duplicate
timestamps, broken OHLC relationships, and non-positive prices. A backtest on
gappy or corrupt data silently overstates the edge, so validation refuses to
bless a series that doesn't pass. Pure functions; the endpoint maps them over
the whole store.
"""
from __future__ import annotations

_TF_S = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
         "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800}


def verify(bars: list, timeframe: str, *, max_gap_report: int = 20) -> dict:
    """Check one chronological bar series. Returns counts, the worst gaps, and
    a verdict: ok / warning (minor gaps) / bad (duplicates, corrupt candles,
    or >1% of the series missing)."""
    step = _TF_S.get(timeframe)
    n = len(bars)
    if n == 0:
        return {"candles": 0, "verdict": "empty", "gaps": [], "duplicates": 0,
                "bad_candles": 0, "missing_total": 0, "missing_pct": 0.0}
    duplicates = bad = 0
    gaps: list[dict] = []
    missing_total = 0
    prev = None
    for b in bars:
        if not (b.low <= b.open <= b.high and b.low <= b.close <= b.high) or b.low <= 0:
            bad += 1
        if prev is not None:
            dt = (b.timestamp - prev.timestamp).total_seconds()
            if dt == 0:
                duplicates += 1
            elif step and dt > step * 1.5:
                missing = int(round(dt / step)) - 1
                missing_total += missing
                if len(gaps) < max_gap_report:
                    gaps.append({"after": prev.timestamp.isoformat(),
                                 "before": b.timestamp.isoformat(),
                                 "missing_candles": missing})
        prev = b
    missing_pct = round(100.0 * missing_total / (n + missing_total), 2)
    if duplicates or bad or missing_pct > 1.0:
        verdict = "bad"
    elif missing_total:
        verdict = "warning"
    else:
        verdict = "ok"
    return {"candles": n, "first": bars[0].timestamp.isoformat(),
            "last": bars[-1].timestamp.isoformat(), "gaps": gaps,
            "duplicates": duplicates, "bad_candles": bad,
            "missing_total": missing_total, "missing_pct": missing_pct,
            "verdict": verdict}


def verify_store(store, symbols, timeframes) -> dict:
    """Verify every cached symbol×timeframe series; overall verdict is the
    worst individual one (empty series are reported but don't fail the store)."""
    rank = {"ok": 0, "warning": 1, "bad": 2}
    reports = []
    worst = "ok"
    for sym in symbols:
        for tf in timeframes:
            r = verify(store.get_bars(sym, tf), tf)
            reports.append({"symbol": sym, "timeframe": tf, **r})
            if rank.get(r["verdict"], 0) > rank.get(worst, 0):
                worst = r["verdict"]
    return {"verdict": worst, "series": reports}
