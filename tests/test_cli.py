"""CLI smoke tests — parser shape, sub-commands, demo end-to-end."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "bot", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=60, **kw,
    )


def test_cli_help():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "backtest" in r.stdout
    assert "multi" in r.stdout
    assert "walkforward" in r.stdout


def test_cli_backtest_demo(tmp_path):
    out_html = tmp_path / "rep.html"
    eq_csv = tmp_path / "eq.csv"
    r = _run([
        "backtest", "--demo", "--symbol", "BTC-USD",
        "--report", str(out_html),
        "--equity-csv", str(eq_csv),
        "--json",
    ])
    assert r.returncode == 0, r.stderr
    # Outputs land on disk and the JSON payload is in stdout.
    assert out_html.exists()
    assert eq_csv.exists()
    assert '"starting_equity"' in r.stdout


def test_cli_multi_runs():
    r = _run(["multi", "--symbols", "BTC-USD,ETH-USD"])
    assert r.returncode == 0, r.stderr
    assert "Start equity" in r.stdout or "starting_equity" in r.stdout


def test_cli_walkforward_runs():
    r = _run(["walkforward", "--demo", "--symbol", "BTC-USD",
              "--train", "400", "--test", "100"])
    assert r.returncode == 0, r.stderr
    assert "windows" in r.stdout.lower()


def test_cli_demo_writes_report(tmp_path, monkeypatch):
    # demo writes report.html into the project root; ensure exit code is 0.
    r = _run(["demo"])
    assert r.returncode == 0, r.stderr
    assert "Wrote" in r.stdout
