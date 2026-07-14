"""Anti-martingale streak risk scaling: half risk after 2 consecutive losses,
quarter after 4, restored by a win. It can only REDUCE risk — never size up —
and it persists / round-trips through the /settings surface."""
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services.controls import TradingControl
from services.signal_pipeline import SignalPipeline


def _pipe(history):
    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led, starting_balance=10_000)
    # exposure caps lifted so sizing differences are visible (the caps clamp
    # both configurations to the same ceiling otherwise)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          adaptive_risk=False, equity_throttle=False,
                          exposure_limit_pct=1.0, max_total_exposure_pct=1.0)
    paper.history = lambda: history  # deterministic closed-trade record
    return pipe


def _loss(i):
    return {"pnl": -50.0, "closed_at": f"2026-01-01T0{i}:00:00+00:00"}


def _win(i):
    return {"pnl": 80.0, "closed_at": f"2026-01-01T0{i}:00:00+00:00"}


def test_streak_factor_ladder():
    assert _pipe([])._streak_factor() == 1.0
    assert _pipe([_loss(1)])._streak_factor() == 1.0            # one loss: full size
    assert _pipe([_loss(1), _loss(2)])._streak_factor() == 0.5  # two: half
    assert _pipe([_loss(1), _loss(2), _loss(3)])._streak_factor() == 0.5
    assert _pipe([_loss(i) for i in range(1, 5)])._streak_factor() == 0.25


def test_win_restores_full_size():
    # most recent trade is a win -> streak broken, full risk again
    pipe = _pipe([_loss(1), _loss(2), _loss(3), _win(4)])
    assert pipe._streak_factor() == 1.0


def test_toggle_disables_scaling():
    pipe = _pipe([_loss(i) for i in range(1, 6)])
    pipe.streak_risk_scaling = False
    assert pipe._streak_factor() == 1.0


def test_sizing_actually_halves_after_two_losses():
    open_payload = {"alert_id": "s1", "symbol": "BTCUSDT", "side": "BUY",
                    "entry": 100.0, "stop": 95.0, "target": 115.0, "confidence": 1.0}
    full = _pipe([]).process(dict(open_payload))
    halved = _pipe([_loss(1), _loss(2)]).process(dict(open_payload, alert_id="s2"))
    assert full.accepted and halved.accepted
    assert abs(halved.fill["size"] - full.fill["size"] * 0.5) < 1e-9
    risk_step = next(s for s in halved.steps if s.rule == "risk")
    assert "streak 0.50" in risk_step.detail


def test_new_settings_roundtrip_through_overrides(tmp_path):
    """streak_risk_scaling + the previously-dropped keys (auto_strategy,
    entry_mode, min_quality_score) must survive a save/load cycle — the
    strategy choice used to silently revert on every restart."""
    from services.runtime_settings import save_overrides, load_overrides
    p = str(tmp_path / "rs.json")
    save_overrides(p, {"streak_risk_scaling": 0, "auto_strategy": "supertrend",
                       "min_quality_score": 70, "entry_mode": "market",
                       "daily_report_hour": 9})
    got = load_overrides(p)
    assert got["streak_risk_scaling"] == 0
    assert got["auto_strategy"] == "supertrend"
    assert got["min_quality_score"] == 70
    assert got["entry_mode"] == "market"
    assert got["daily_report_hour"] == 9


def test_scaling_never_increases_risk():
    # a long winning streak must NOT size up (anti-martingale, not martingale)
    open_payload = {"alert_id": "w1", "symbol": "BTCUSDT", "side": "BUY",
                    "entry": 100.0, "stop": 95.0, "target": 115.0, "confidence": 1.0}
    base = _pipe([]).process(dict(open_payload))
    hot = _pipe([_win(i) for i in range(1, 6)]).process(dict(open_payload, alert_id="w2"))
    assert abs(hot.fill["size"] - base.fill["size"]) < 1e-9
