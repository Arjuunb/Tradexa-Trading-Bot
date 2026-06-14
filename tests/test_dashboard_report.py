"""The 10-panel server-rendered dashboard renders from real engine output."""
from bot.backtester import Backtester
from bot.dashboard_report import render_dashboard_html
from bot.data.synthetic import generate_bars
from bot.events import EventBus
from bot.risk import RiskManager
from bot.strategies import SupportResistanceRejection


def _run(symbol="BTC-USD", n=1500, seed=1):
    bars = generate_bars(n, "1h", seed=seed)
    bus = EventBus()
    risk = RiskManager()
    result = Backtester(SupportResistanceRejection(symbol), bars,
                        risk=risk, bus=bus).run()
    return result, bars, bus.replay(), risk


def test_dashboard_has_all_ten_panels():
    result, bars, events, risk = _run()
    doc = render_dashboard_html(
        result=result, bars=bars, events=events, symbol="BTC-USD",
        risk_cfg=risk.cfg,
    )
    assert doc.startswith("<!doctype html>")
    # Panel 1 is the header (no numbered label).
    assert "TRADING BOT DASHBOARD" in doc
    assert "EMERGENCY STOP" in doc
    for marker in (
        "2 · Account Summary", "3 · Active Bot Settings",
        "4 · Live Market Panel", "5 · Signal Panel", "6 · Open Positions",
        "7 · Risk Guard", "8 · Trade History", "9 · Performance Analytics",
        "10 · Bot Logs",
    ):
        assert marker in doc, f"missing panel: {marker}"


def test_dashboard_renders_three_charts_and_no_external_refs():
    result, bars, events, risk = _run()
    doc = render_dashboard_html(result=result, bars=bars, events=events,
                                symbol="BTC-USD", risk_cfg=risk.cfg)
    # candlestick + equity + drawdown
    assert doc.count("<svg") >= 3
    # Fully self-contained: no external scripts/styles/images.
    assert "http://" not in doc and "https://" not in doc
    assert "<script" not in doc


def test_dashboard_handles_zero_trade_run():
    # Very short series -> strategy never fires; must still render cleanly.
    bars = generate_bars(60, "1h", seed=5)
    bus = EventBus()
    risk = RiskManager()
    result = Backtester(SupportResistanceRejection("X"), bars,
                        risk=risk, bus=bus).run()
    doc = render_dashboard_html(result=result, bars=bars, events=bus.replay(),
                                symbol="X", risk_cfg=risk.cfg)
    assert "No positions taken" in doc
    assert "10 · Bot Logs" in doc
