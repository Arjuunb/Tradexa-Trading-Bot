"""Strategy lifecycle state.

Contract: every stage's state is derived from evidence that exists, ordering is
enforced honestly, and a stage nobody records is reported as unknown rather than
as skipped.
"""
import pytest

from services import strategy_lifecycle as sl

SPEC = {
    "id": "s1", "name": "EMA Trend", "symbol": "BTCUSDT", "timeframe": "4h",
    "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50}]},
    "stop": {"type": "atr", "mult": 1.5}, "target": {"type": "rr", "rr": 2},
    "risk_per_trade_pct": 0.01,
}

BT = {"total_trades": 53, "net_r": 14.26, "profit_factor": 1.46}


def _stage(out, key):
    return next(s for s in out["stages"] if s["key"] == key)


def _states(out):
    return {s["key"]: s["state"] for s in out["stages"]}


# ------------------------------------------------------------------ shape

def test_all_nine_stages_are_reported_in_order():
    out = sl.evaluate(spec=SPEC)
    assert [s["n"] for s in out["stages"]] == list(range(1, 10))
    assert out["total"] == 9


def test_every_stage_names_the_page_that_does_the_work():
    """A lifecycle view that describes a destination instead of linking to it is
    a diagram, not navigation."""
    for s in sl.evaluate(spec=SPEC)["stages"]:
        assert s["page"] and s["purpose"]


def test_a_missing_strategy_is_unavailable_not_an_empty_lifecycle():
    out = sl.evaluate(spec=None)
    assert out["available"] is False and out["stages"] == []


# ------------------------------------------------------------- compilation

def test_a_spec_with_rules_has_compiled():
    assert _stage(sl.evaluate(spec=SPEC), "compile")["state"] == sl.DONE


def test_a_spec_with_no_rules_has_not():
    out = sl.evaluate(spec={**SPEC, "entry": {"op": "AND", "rules": []}})
    assert _stage(out, "compile")["state"] == sl.READY


# ---------------------------------------------------------------- ordering

def test_everything_downstream_is_blocked_without_rules():
    out = sl.evaluate(spec={"id": "x", "name": "Empty"})
    st = _states(out)
    assert st["backtest"] == sl.BLOCKED
    assert st["review"] == sl.BLOCKED
    assert st["paper"] == sl.BLOCKED
    assert _stage(out, "backtest")["blocked_by"] == "compile"


def test_review_is_blocked_until_the_backtest_has_enough_trades():
    thin = sl.evaluate(spec=SPEC, backtest={"total_trades": 4})
    assert _stage(thin, "review")["state"] == sl.BLOCKED
    assert "noise" in _stage(thin, "review")["detail"]

    ok = sl.evaluate(spec=SPEC, backtest=BT)
    assert _stage(ok, "review")["state"] == sl.READY


def test_live_deployment_is_blocked_until_there_is_paper_history():
    out = sl.evaluate(spec=SPEC, backtest=BT, paper={"trades": 3})
    d = _stage(out, "deploy")
    assert d["state"] == sl.BLOCKED and d["blocked_by"] == "paper"


def test_monitoring_is_blocked_until_something_is_deployed():
    out = sl.evaluate(spec=SPEC, backtest=BT)
    assert _stage(out, "monitor")["blocked_by"] == "deploy"


def test_publishing_is_blocked_until_the_backtest_can_be_verified():
    out = sl.evaluate(spec=SPEC, backtest={"total_trades": 4})
    assert _stage(out, "publish")["state"] == sl.BLOCKED


# ------------------------------------------------------- unrecorded stages

def test_replay_is_unknown_not_pending():
    """Replay leaves no trace. Calling it 'not done' would nag people into
    redoing work they may already have done."""
    r = _stage(sl.evaluate(spec=SPEC, backtest=BT), "replay")
    assert r["state"] == sl.UNKNOWN
    assert "not recorded" in r["detail"]


def test_unknown_stages_are_counted_separately_from_completed_ones():
    out = sl.evaluate(spec=SPEC, backtest=BT)
    assert out["unknown"] == 1
    assert out["completed"] < out["total"]


# ------------------------------------------------------------- completion

def test_a_fully_progressed_strategy_reports_its_evidence():
    out = sl.evaluate(
        spec={**SPEC, "versions": [{"v": 1}, {"v": 2}]},
        backtest=BT,
        paper={"trades": 40, "net_r": 8.0, "attributed": True},
        deployed=True,
        monitor={"status": "in_line", "findings": []},
        listing={"verified": {"metrics": {"total_trades": 53}},
                 "rating": {"average": 4.0}, "imports": 3},
        shares={"grants": {"bob": {"role": "editor"}}},
        comments=2)
    st = _states(out)
    for key in ("compile", "backtest", "paper", "deploy", "monitor",
                "publish", "collaborate"):
        assert st[key] == sl.DONE, key
    assert out["completed"] == 7


def test_review_is_never_marked_done_because_reading_it_leaves_no_artifact():
    """Like replay, a review produces no stored record. Marking it complete
    would claim knowledge of something nobody wrote down; leaving it READY is
    accurate — the review is genuinely available at any time."""
    out = sl.evaluate(spec=SPEC, backtest=BT, paper={"trades": 40},
                      deployed=True, monitor={"status": "in_line"})
    assert _stage(out, "review")["state"] == sl.READY


def test_the_next_action_is_the_first_ready_stage():
    out = sl.evaluate(spec=SPEC, backtest=BT)
    assert out["next"]["key"] == "review"


def test_evidence_carries_real_numbers_not_labels():
    out = sl.evaluate(spec=SPEC, backtest=BT)
    ev = {e["stat"]: e["value"] for e in _stage(out, "backtest")["evidence"]}
    assert ev["trades"] == 53 and ev["net R"] == 14.26


# -------------------------------------------------------------- attribution

def test_unattributed_paper_trades_are_flagged_as_the_accounts_not_the_strategys():
    """Before per-strategy attribution these trades belong to whatever was
    running. Presenting them as this strategy's record would be a lie."""
    out = sl.evaluate(spec=SPEC, backtest=BT,
                      paper={"trades": 40, "attributed": False})
    assert "not this" in _stage(out, "paper")["caveat"]


def test_attributed_paper_trades_carry_no_caveat():
    out = sl.evaluate(spec=SPEC, backtest=BT,
                      paper={"trades": 40, "attributed": True})
    assert "caveat" not in _stage(out, "paper")


def test_a_partial_paper_sample_says_how_far_along_it_is():
    out = sl.evaluate(spec=SPEC, backtest=BT, paper={"trades": 5})
    d = _stage(out, "paper")
    assert d["state"] == sl.READY
    assert f"5 of {sl.MIN_PAPER_TRADES}" in d["detail"]


# ------------------------------------------------------------------ endpoint

@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    from services.custom_store import CustomStore
    monkeypatch.setattr(webhook_api, "custom_store",
                        CustomStore(str(tmp_path / "custom.json")))
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def test_lifecycle_endpoint_returns_real_state(client):
    import webhook_api
    saved = webhook_api.custom_store.save(dict(SPEC))
    r = client.get(f"/strategy/custom/{saved['id']}/lifecycle")
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is True
    assert len(j["stages"]) == 9
    assert _stage(j, "compile")["state"] == sl.DONE


def test_lifecycle_endpoint_404s_for_a_missing_strategy(client):
    assert client.get("/strategy/custom/nope/lifecycle").status_code == 404


# ------------------------------------------- replay timeframe honesty

def test_replay_reports_when_it_substitutes_the_timeframe():
    """Replay only executes 1m/3m/5m/15m. Running a 4h strategy at 15m is a
    DIFFERENT strategy from the one that was backtested — silently substituting
    would break the rule that every mode runs the same strategy."""
    from services.replay import build_replay
    m = build_replay("BTCUSDT", exec_tf="4h", limit=300)["meta"]
    assert m["timeframe_substituted"] is True
    assert m["requested_timeframe"] == "4h" and m["timeframe"] == "15m"
    assert "not at 4h" in m["timeframe_note"]


def test_a_supported_timeframe_reports_no_substitution():
    from services.replay import build_replay
    m = build_replay("BTCUSDT", exec_tf="15m", limit=300)["meta"]
    assert m["timeframe_substituted"] is False
    assert m["timeframe_note"] is None
