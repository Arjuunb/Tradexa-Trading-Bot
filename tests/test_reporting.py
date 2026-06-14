"""HTML report exporter — verify a self-contained file lands on disk."""
from pathlib import Path

from bot.backtester import Backtester
from bot.data.synthetic import generate_bars
from bot.reporting import render_report, render_report_html
from bot.strategies import SupportResistanceRejection


def test_render_report_writes_file(tmp_path):
    bars = generate_bars(400, "1h", seed=1)
    bt = Backtester(SupportResistanceRejection("X"), bars)
    res = bt.run()
    out = tmp_path / "r.html"
    path = render_report(res, output_path=str(out))
    assert Path(path).exists()
    body = Path(path).read_text()
    assert "<svg" in body
    assert "Backtest Report" in body
    # Stdlib-only -> no external resources allowed
    assert "http://" not in body or "/svg" in body  # only the svg ns URL ok


def test_render_report_html_returns_string_no_file(tmp_path):
    """The string renderer must produce the same document without touching disk."""
    bars = generate_bars(400, "1h", seed=1)
    res = Backtester(SupportResistanceRejection("X"), bars).run()
    doc = render_report_html(res, title="Inline Report")
    assert isinstance(doc, str)
    assert doc.startswith("<!doctype html>")
    assert "<svg" in doc and "Inline Report" in doc
    # Writer and string renderer agree.
    written = Path(render_report(res, title="Inline Report",
                                 output_path=str(tmp_path / "r.html"))).read_text()
    assert written == doc
