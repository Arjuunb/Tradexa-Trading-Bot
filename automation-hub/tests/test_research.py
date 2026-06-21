"""Research Lab (#15): run + save A/B experiments, list, report."""
import pytest

from services.research import ResearchStore, report_markdown, run_research


def _spec(fast, slow):
    return {"symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": fast, "slow": slow, "dir": "above"}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14},
            "target": {"type": "rr", "rr": 2.0}, "risk_per_trade_pct": 0.01, "min_score": 60}


def test_run_research_produces_record():
    rec = run_research("EMA tweak", _spec(20, 50), _spec(9, 33), bars=2500, label_a="20/50", label_b="9/33")
    assert rec["id"] and rec["name"] == "EMA tweak"
    assert rec["verdict"] in ("improvement", "overfit", "marginal", "no_improvement")
    assert "experiment" in rec and rec["experiment"]["a"]["label"] == "20/50"


def test_store_save_list_get_delete(tmp_path):
    rs = ResearchStore(str(tmp_path / "r.json"))
    rec = run_research("X", _spec(20, 50), _spec(10, 30), bars=2500)
    rs.save(rec)
    lst = rs.list()
    assert len(lst) == 1 and "experiment" not in lst[0]     # summary view is light
    assert rs.get(rec["id"])["experiment"]                  # full record retains payload
    assert rs.delete(rec["id"]) is True and rs.list() == []


def test_report_markdown_has_sections():
    rec = run_research("Report test", _spec(20, 50), _spec(8, 21), bars=2500, label_a="A", label_b="B")
    md = report_markdown(rec)
    assert md.startswith("# Research")
    assert "Verdict:" in md and "Train net R" in md and "Out-of-sample gain" in md


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    webhook_api.research_store = ResearchStore(str(tmp_path / "r.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"
H = {"X-Webhook-Secret": SECRET}


def test_research_endpoints(client):
    payload = {"name": "EMA AB", "spec_a": _spec(20, 50), "spec_b": _spec(9, 33), "bars": 2500}
    assert client.post("/research/run", json=payload).status_code == 401
    rec = client.post("/research/run", json=payload, headers=H).json()
    rid = rec["id"]
    assert client.get("/research").json()["experiments"][0]["id"] == rid
    rep = client.get(f"/research/{rid}/report").json()
    assert "# Research" in rep["report"]
    assert client.delete(f"/research/{rid}", headers=H).json()["deleted"] is True
