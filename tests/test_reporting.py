"""HTML report exporter — verify a self-contained file lands on disk."""
from pathlib import Path

from bot.backtester import Backtester
from bot.data.synthetic import generate_bars
from bot.reporting import render_report
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
