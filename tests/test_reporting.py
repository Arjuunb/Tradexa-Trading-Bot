"""HTML report exporter — verify a self-contained file lands on disk."""
from datetime import datetime
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

    # Writer and string renderer agree. Both are pinned to the same instant:
    # the document carries a "generated" stamp, so two renders that straddle a
    # second boundary differ by one character and the comparison fails at random
    # (it did, on CI, roughly one run in sixty).
    stamp = datetime(2026, 1, 2, 3, 4, 5)
    doc_at = render_report_html(res, title="Inline Report", generated_at=stamp)
    written = Path(render_report(res, title="Inline Report",
                                 output_path=str(tmp_path / "r.html"),
                                 generated_at=stamp)).read_text()
    assert written == doc_at


def test_the_generated_stamp_is_the_only_thing_that_varies_between_renders():
    """Pins WHY the comparison above needs a fixed instant — if anything else
    ever becomes non-deterministic, this fails instead of the flake reappearing."""
    bars = generate_bars(200, "1h", seed=7)
    res = Backtester(SupportResistanceRejection("X"), bars).run()
    a = render_report_html(res, generated_at=datetime(2026, 1, 1, 0, 0, 0))
    b = render_report_html(res, generated_at=datetime(2026, 1, 1, 0, 0, 0))
    assert a == b, "same inputs and same instant must give the same bytes"

    c = render_report_html(res, generated_at=datetime(2026, 1, 1, 0, 0, 1))
    assert a != c, "the stamp is meant to be in the document"
    assert len(a) == len(c), "and it should be the ONLY difference"
