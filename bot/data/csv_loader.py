"""CSV → list[Bar] loader. Stdlib only.

Supported header variants (case-insensitive):
- ``timestamp,open,high,low,close,volume``
- ``time,open,high,low,close,volume``
- ``date,open,high,low,close,volume``

The timestamp column accepts:
- ISO-8601 strings (``2025-01-02T15:00:00Z`` or ``2025-01-02 15:00:00+00:00``)
- Unix seconds (10-digit int/float)
- Unix milliseconds (13-digit int/float)

All times are normalised to timezone-aware UTC ``datetime`` objects.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from bot.types import Bar


_TS_KEYS = ("timestamp", "time", "date", "datetime")


def _parse_ts(raw: str) -> datetime:
    raw = raw.strip()
    # numeric epoch?
    try:
        num = float(raw)
        # heuristic: 13-digit → ms, 10-digit → s
        if num > 1e12:
            return datetime.fromtimestamp(num / 1000.0, tz=timezone.utc)
        if num > 1e9:
            return datetime.fromtimestamp(num, tz=timezone.utc)
    except ValueError:
        pass
    # ISO
    s = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm(s: str) -> str:
    return s.strip().lower()


def load_csv_bars(path: str | Path) -> list[Bar]:
    """Load a single-symbol OHLCV CSV. Returns chronologically sorted bars."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {p}")
    bars: list[Bar] = []
    with p.open("r", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV {p} has no header row")
        cols = {_norm(c): c for c in reader.fieldnames}
        ts_col = next((cols[k] for k in _TS_KEYS if k in cols), None)
        if ts_col is None:
            raise ValueError(
                f"CSV {p} missing timestamp column. "
                f"Expected one of {_TS_KEYS}. Got {reader.fieldnames}"
            )
        for k in ("open", "high", "low", "close"):
            if k not in cols:
                raise ValueError(f"CSV {p} missing column '{k}'")
        for row in reader:
            try:
                bars.append(Bar(
                    timestamp=_parse_ts(row[ts_col]),
                    open=float(row[cols["open"]]),
                    high=float(row[cols["high"]]),
                    low=float(row[cols["low"]]),
                    close=float(row[cols["close"]]),
                    volume=float(row[cols["volume"]]) if "volume" in cols and row[cols["volume"]] else 0.0,
                ))
            except (KeyError, ValueError) as e:
                raise ValueError(f"Bad row in {p}: {row} ({e})") from e
    bars.sort(key=lambda b: b.timestamp)
    return bars


def load_csv_bars_multi(paths: dict[str, str | Path]) -> dict[str, list[Bar]]:
    """Load several symbols. Returns ``{symbol: [Bar, ...]}``."""
    out: dict[str, list[Bar]] = {}
    for sym, p in paths.items():
        out[sym] = load_csv_bars(p)
    return out


def write_csv_bars(path: str | Path, bars: Iterable[Bar]) -> None:
    """Write Bars back to CSV in the canonical format."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for b in bars:
            ts = b.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            w.writerow([ts.isoformat(), b.open, b.high, b.low, b.close, b.volume])
