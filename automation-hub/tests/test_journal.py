"""Trade Journal (#11)."""
import pytest

from services.journal import JournalStore, auto_entry


def _trade(tid, rr, loss=None, reasons=None, result=None):
    return {"id": tid, "side": "long", "rr": rr, "entry": 100, "exit": 102,
            "entry_idx": 10, "exit_idx": 20, "loss_analysis": loss,
            "entry_reasons": reasons or ["4H bullish"], "result": result}


def test_auto_entry_seeds_notes_snapshot_and_lessons():
    e = auto_entry(_trade(1, -1.0, loss="Entered in choppy / unclear conditions."),
                   symbol="BTCUSDT", strategy="Decision Brain", timeframe="15m")
    assert e["snapshot"]["symbol"] == "BTCUSDT" and e["snapshot"]["entry_idx"] == 10
    assert e["notes"] and e["mistakes"] == ["Entered in choppy / unclear conditions."]
    assert any("choppy" in l.lower() or "ranging" in l.lower() for l in e["lessons"])
    assert e["emotions"] == "" and e["auto"] is True


def test_winner_seeds_positive_lesson():
    e = auto_entry(_trade(2, 2.0, result="Winner"), symbol="ETHUSDT", strategy="EMA 8/30", timeframe="4h")
    assert e["mistakes"] == [] and e["lessons"]


def test_store_add_dedupes_and_lists(tmp_path):
    js = JournalStore(str(tmp_path / "j.json"))
    trades = [_trade(1, 1.0), _trade(2, -1.0, loss="Stopped almost immediately — false breakout.")]
    added = js.add_from_trades(trades, symbol="BTCUSDT", strategy="X", timeframe="15m")
    assert len(added) == 2
    # re-journaling the same trades adds nothing (dedupe on trade_id)
    again = js.add_from_trades(trades, symbol="BTCUSDT", strategy="X", timeframe="15m")
    assert again == []
    assert len(js.list()) == 2


def test_store_update_edits_human_fields(tmp_path):
    js = JournalStore(str(tmp_path / "j.json"))
    e = js.add(auto_entry(_trade(1, 1.0), symbol="BTCUSDT", strategy="X", timeframe="15m"))
    upd = js.update(e["id"], {"notes": "felt rushed", "emotions": "anxious", "tags": ["fomo"]})
    assert upd["notes"] == "felt rushed" and upd["emotions"] == "anxious" and upd["tags"] == ["fomo"]
    assert js.update("nope", {"notes": "x"}) is None
    assert js.delete(e["id"]) is True


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    from services.journal import JournalStore
    webhook_api.journal_store = JournalStore(str(tmp_path / "j.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"
H = {"X-Webhook-Secret": SECRET}


def test_journal_endpoints(client):
    assert client.get("/journal").json()["entries"] == []
    assert client.post("/journal/from-replay", params={"symbol": "BTCUSDT", "strategy": "EMA 8/30",
                                                      "timeframe": "15m", "limit": 600}).status_code == 401
    gen = client.post("/journal/from-replay", params={"symbol": "BTCUSDT", "strategy": "EMA 8/30",
                                                     "timeframe": "15m", "limit": 600}, headers=H).json()
    assert gen["added"] >= 0 and "entries" in gen
    entries = client.get("/journal").json()["entries"]
    if entries:
        eid = entries[0]["id"]
        upd = client.patch(f"/journal/{eid}", json={"emotions": "calm"}, headers=H).json()
        assert upd["emotions"] == "calm"
