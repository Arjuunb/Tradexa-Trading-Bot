"""Strategy Marketplace (#1): catalog, favorite, tags, clone, ranking."""
import pytest

from services.custom_store import CustomStore
from services.marketplace import catalog, clone_template


@pytest.fixture()
def store(tmp_path):
    return CustomStore(str(tmp_path / "custom.json"))


def test_catalog_has_templates_and_library(store):
    store.save({"name": "My EMA", "side": "long",
                "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 9, "slow": 21}]}})
    cat = catalog(store)
    assert cat["counts"]["library"] == 1
    names = {t["name"] for t in cat["templates"]}
    assert {"Decision Brain", "Supply/Demand", "EMA 20/50"} <= names      # built-ins listed
    assert any(t["clonable"] for t in cat["templates"])                   # rule-based ones clonable


def test_favorite_and_tags(store):
    s = store.save({"name": "Fav strat", "side": "long"})
    store.set_favorite(s["id"], True)
    store.set_tags(s["id"], ["scalp", "btc", "  ", "trend"])
    cat = catalog(store)
    lib = cat["library"][0]
    assert lib["favorite"] is True
    assert lib["tags"] == ["scalp", "btc", "trend"]                        # blanks dropped
    assert "scalp" in cat["tags"] and cat["counts"]["favorites"] == 1


def test_favorites_sort_first(store):
    store.save({"name": "Plain"})
    fav = store.save({"name": "Star"})
    store.set_favorite(fav["id"], True)
    assert catalog(store)["library"][0]["name"] == "Star"


def test_clone_rulebased_template_into_library(store):
    r = clone_template(store, "EMA 20/50")
    assert "error" not in r and r["id"]
    assert r["entry"]["rules"] and r["timeframe"]
    assert catalog(store)["counts"]["library"] == 1
    # built-in engine strategies cannot be cloned (they are activated instead)
    assert "error" in clone_template(store, "Decision Brain")
    assert "error" in clone_template(store, "Nope")


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture()
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    webhook_api.custom_store = CustomStore(str(tmp_path / "c.json"))
    app = FastAPI(); app.include_router(webhook_api.router)
    return TestClient(app)


SECRET = "dev-webhook-secret"
H = {"X-Webhook-Secret": SECRET}


def test_marketplace_endpoints(client):
    cat = client.get("/marketplace").json()
    assert "templates" in cat and "library" in cat
    # clone a template (secret-gated)
    assert client.post("/marketplace/clone-template", json={"template": "EMA 8/30"}).status_code == 401
    cloned = client.post("/marketplace/clone-template", json={"template": "EMA 8/30"}, headers=H).json()
    sid = cloned["id"]
    # favorite + tags
    fav = client.post(f"/marketplace/{sid}/favorite", headers=H).json()
    assert fav["favorite"] is True
    tagged = client.post(f"/marketplace/{sid}/tags", json={"tags": ["breakout"]}, headers=H).json()
    assert tagged["tags"] == ["breakout"]
    assert client.get("/marketplace").json()["counts"]["library"] == 1


def test_marketplace_rank_real_data(client):
    body = client.get("/marketplace/rank", params={"symbol": "BTCUSDT", "timeframe": "15m",
                                                   "strategies": "EMA 8/30,EMA 20/50", "limit": 600}).json()
    assert len(body["ranking"]) == 2
    nets = [r["net_r"] for r in body["ranking"]]
    assert nets == sorted(nets, reverse=True) and body["best"]
