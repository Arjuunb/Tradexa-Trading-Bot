"""CSV loader: format variants, ISO and epoch timestamps, missing columns."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bot.data.csv_loader import load_csv_bars, write_csv_bars
from bot.types import Bar


def _write(p: Path, rows: list[list]):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)


def test_load_iso_timestamps(tmp_path):
    p = tmp_path / "iso.csv"
    _write(p, [
        ["timestamp", "open", "high", "low", "close", "volume"],
        ["2025-01-02T15:00:00Z", 100, 101, 99, 100.5, 1000],
        ["2025-01-02T16:00:00Z", 100.5, 102, 100, 101.5, 1200],
    ])
    bars = load_csv_bars(p)
    assert len(bars) == 2
    assert bars[0].timestamp == datetime(2025, 1, 2, 15, tzinfo=timezone.utc)
    assert bars[0].close == 100.5


def test_load_epoch_ms_timestamps(tmp_path):
    p = tmp_path / "epoch.csv"
    _write(p, [
        ["time", "open", "high", "low", "close", "volume"],
        [1735830000000, 100, 101, 99, 100.5, 1000],  # 2025-01-02 15:00 UTC
    ])
    bars = load_csv_bars(p)
    assert bars[0].timestamp == datetime(2025, 1, 2, 15, tzinfo=timezone.utc)


def test_load_sorts_chronologically(tmp_path):
    p = tmp_path / "out.csv"
    _write(p, [
        ["timestamp", "open", "high", "low", "close", "volume"],
        ["2025-01-02T16:00:00Z", 1, 1, 1, 1, 0],
        ["2025-01-02T15:00:00Z", 2, 2, 2, 2, 0],
    ])
    bars = load_csv_bars(p)
    assert bars[0].timestamp < bars[1].timestamp


def test_load_missing_required_column_raises(tmp_path):
    p = tmp_path / "bad.csv"
    _write(p, [
        ["timestamp", "open", "high", "close", "volume"],  # no low
        ["2025-01-02T15:00:00Z", 100, 101, 100.5, 1000],
    ])
    with pytest.raises(ValueError):
        load_csv_bars(p)


def test_roundtrip_write_then_read(tmp_path):
    bars = [
        Bar(datetime(2025, 1, 2, 15, tzinfo=timezone.utc), 100, 101, 99, 100.5, 1000),
        Bar(datetime(2025, 1, 2, 16, tzinfo=timezone.utc), 100.5, 102, 100, 101.5, 1200),
    ]
    p = tmp_path / "rt.csv"
    write_csv_bars(p, bars)
    out = load_csv_bars(p)
    assert len(out) == 2
    assert out[0].close == 100.5 and out[1].close == 101.5
