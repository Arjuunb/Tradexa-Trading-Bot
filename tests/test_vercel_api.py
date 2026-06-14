"""The Vercel serverless entry point (api/index.py) builds a real report."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "vercel_api_index", ROOT / "api" / "index.py"
)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)


def test_run_dashboard_html_default_view():
    doc = api._run_dashboard_html("BTC-USD", n=1500, seed=1)
    assert doc.startswith("<!doctype html>")
    assert "TRADING BOT DASHBOARD" in doc
    assert "10 · Bot Logs" in doc


def test_run_report_html_uses_bundled_sample():
    doc = api._run_report_html("BTC-USD", n=2000, seed=1)
    assert doc.startswith("<!doctype html>")
    assert "<svg" in doc
    assert "bundled sample data" in doc  # data/samples/BTC-USD.csv exists


def test_run_report_html_falls_back_to_synthetic():
    doc = api._run_report_html("NO-SUCH-SYMBOL", n=500, seed=3)
    assert "synthetic data" in doc
    assert "<svg" in doc


def test_int_arg_clamps_and_defaults():
    assert api._int_arg({"bars": ["5"]}, "bars", 2000, 200, 20000) == 200      # clamp low
    assert api._int_arg({"bars": ["999999"]}, "bars", 2000, 200, 20000) == 20000  # clamp high
    assert api._int_arg({"bars": ["nope"]}, "bars", 2000, 200, 20000) == 2000   # bad -> default
    assert api._int_arg({}, "bars", 2000, 200, 20000) == 2000                   # missing -> default
