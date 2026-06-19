"""Evolution Engine: sentiment labelling, lessons, upgrades + human-approval
lifecycle, strategy versions, and the A/B experiment lab."""
import pytest

from services.sentiment import label_mood, confidence_filter, risk_mode, market_sentiment
from services.lessons import lessons_from_results, tag_trade, LessonStore
from services.evolution import (UpgradeStore, StrategyVersionStore, suggest_improvements,
                                run_experiment, BOT_ALLOWED_STATUSES)


# ---- sentiment ----
def test_label_mood_thresholds():
    assert label_mood(5) == "Panic"
    assert label_mood(20) == "Extreme Fear"
    assert label_mood(50) == "Neutral"
    assert label_mood(80) == "Extreme Greed"
    assert label_mood(95) == "Euphoria"


def test_confidence_filter_reduces_long_in_greed():
    assert confidence_filter("Extreme Greed")["long"] < 1.0
    assert confidence_filter("Extreme Greed")["short"] == 1.0
    assert confidence_filter("Neutral") == {"long": 1.0, "short": 1.0, "note": confidence_filter("Neutral")["note"]}


def test_market_sentiment_never_fakes_when_offline():
    s = market_sentiment()           # no network in tests -> available False, not fabricated
    assert "available" in s
    if not s["available"]:
        assert s["mood"] is None and "not faking" in s["note"].lower()
    assert isinstance(risk_mode("Neutral"), str)


# ---- lessons (deterministic, from a crafted losing bundle) ----
def _losing_bundle():
    trades = [{"rr": -1, "regime": "Ranging", "score": 40, "bars_held": 1, "exit_reason": "stop",
               "loss_analysis": "choppy", "side": "long", "entry_time": "2024-01-01T03:00:00",
               "entry_reasons": []} for _ in range(5)]
    trades.append({"rr": 1.0, "regime": "Trending", "score": 80, "bars_held": 8, "side": "long",
                   "exit_reason": "target", "entry_time": "2024-01-01T10:00:00", "entry_reasons": ["sweep"]})
    diag = {"worst_regime": {"name": "Ranging", "net_r": -5.0, "trades": 5, "win_rate": 0},
            "worst_session": {"name": "Asia", "net_r": -5.0, "trades": 5, "win_rate": 0},
            "avg_losing_setup_score": 40, "overtrading": True, "trades_per_day": 5}
    return {"trades": trades, "stats": {"win_rate": 58, "profit_factor": 1.05}, "diagnosis": diag}


def test_lessons_fire_on_losing_evidence():
    lessons = lessons_from_results(_losing_bundle(), symbol="BTCUSDT", strategy="SMC")
    assert lessons
    text = " ".join(l["lesson"] + l["suggested_fix"] for l in lessons)
    assert "Ranging" in text                  # worst-regime lesson
    assert any("regime filter" in l["suggested_fix"].lower() for l in lessons)
    assert all(0 <= l["confidence"] <= 100 for l in lessons)


def test_lessons_require_minimum_sample():
    bundle = {"trades": [{"rr": -1}], "stats": {}, "diagnosis": {}}
    assert lessons_from_results(bundle, symbol="X", strategy="Y") == []


def test_tag_trade_winner_and_loser():
    assert "Choppy market" in tag_trade({"rr": -1, "regime": "Ranging", "exit_reason": "stop", "bars_held": 1})
    assert "Strong trend alignment" in tag_trade({"rr": 2, "regime": "Trending", "score": 80, "entry_reasons": []})


# ---- lesson store ----
def test_lesson_store_dedup_and_status(tmp_path):
    st = LessonStore(str(tmp_path / "l.json"))
    ls = lessons_from_results(_losing_bundle(), symbol="BTCUSDT", strategy="SMC")
    added = st.add_many(ls)
    assert added
    assert st.add_many(ls) == []                # de-duplicated
    lid = added[0]["id"]
    assert st.set_status(lid, "Approved")["status"] == "Approved"
    assert st.set_status(lid, "Bogus") is None
    assert st.weekly_count() >= 1


# ---- upgrades + human approval ----
def test_upgrade_lifecycle_human_only(tmp_path):
    st = UpgradeStore(str(tmp_path / "u.json"))
    sug = suggest_improvements(_losing_bundle(), symbol="BTCUSDT", strategy="SMC")
    assert sug and all(k in sug[0] for k in ("title", "reason", "evidence", "expected_benefit",
                                             "risk", "backtest_required"))
    added = st.add_many(sug)
    uid = added[0]["id"]
    assert added[0]["status"] == "Suggested"
    # the bot may advance testing stages but NEVER approve
    assert st.set_status(uid, "Backtested", by="bot")["status"] == "Backtested"
    assert "error" in st.set_status(uid, "Approved", by="bot")
    assert "Approved" not in BOT_ALLOWED_STATUSES
    # a human can approve
    assert st.set_status(uid, "Approved", by="human")["status"] == "Approved"


# ---- versions ----
def test_version_store_increments_and_picks_best(tmp_path):
    st = StrategyVersionStore(str(tmp_path / "v.json"))
    v1 = st.add_version("SMC", {"rr": 2}, {"net_r": 3.0, "profit_factor": 1.2})
    v2 = st.add_version("SMC", {"rr": 2.5}, {"net_r": 8.0, "profit_factor": 1.6})
    assert v1["version"] == 1 and v2["version"] == 2
    cmp = st.compare("SMC")
    assert cmp["best"] == "SMC v2" and len(cmp["versions"]) == 2


# ---- experiment lab ----
def test_experiment_returns_verdict_and_warnings():
    base = {"symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14}, "target": {"type": "rr", "rr": 2.0},
            "risk_per_trade_pct": 0.01, "min_score": 60}
    variant = {**base, "min_score": 75}
    exp = run_experiment(base, variant, bars=3000)
    assert exp["verdict"] in ("improvement", "overfit", "marginal", "no_improvement")
    assert "a" in exp and "b" in exp and isinstance(exp["warnings"], list)
    assert "test" in exp["a"] and "train" in exp["b"]


# ---- endpoints ----
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    webhook_api.lesson_store = LessonStore(str(tmp_path / "l.json"))
    webhook_api.upgrade_store = UpgradeStore(str(tmp_path / "u.json"))
    webhook_api.version_store = StrategyVersionStore(str(tmp_path / "v.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"


def test_sentiment_and_dashboard_endpoints(client):
    s = client.get("/evolution/sentiment").json()
    assert "available" in s
    d = client.get("/evolution/dashboard").json()
    assert "workflow" in d and "live_rule" in d and "human approval" in d["live_rule"].lower()


def test_learn_is_gated_and_records(client):
    assert client.post("/evolution/learn").status_code == 401
    r = client.post("/evolution/learn", params={"symbol": "BTCUSDT", "limit": 800},
                    headers={"X-Webhook-Secret": SECRET})
    assert r.status_code == 200
    assert "lessons" in r.json() and "upgrades" in r.json()
    assert client.get("/evolution/lessons").status_code == 200


def test_experiment_endpoint(client):
    base = {"symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 1.5}, "target": {"type": "rr", "rr": 2.0},
            "risk_per_trade_pct": 0.01}
    body = client.post("/evolution/experiment", json={"base": base, "variant": {**base, "min_score": 75}, "bars": 2500}).json()
    assert body["verdict"] in ("improvement", "overfit", "marginal", "no_improvement")
