"""Persistent user workspace: per-user settings survive logout/re-login, are
strictly isolated between users, reset ONLY explicitly, and the engine's
watchlist survives a server restart."""
import pytest
from fastapi.testclient import TestClient

from database.store import SqliteStore


# ─────────────────────────────── store layer ───────────────────────────────
def test_settings_roundtrip_and_isolation(tmp_path):
    st = SqliteStore(tmp_path / "hub.db")
    st.create_user("alice", "password-a1")
    st.create_user("bob", "password-b1")

    st.set_user_settings("alice", "dashboard", {"chartTf": "15m", "collapsed": ["risk"]})
    st.set_user_settings("bob", "dashboard", {"chartTf": "1h"})

    assert st.get_user_settings("alice", "dashboard")["chartTf"] == "15m"
    assert st.get_user_settings("bob", "dashboard")["chartTf"] == "1h"
    # one user's data never bleeds into another's
    assert "collapsed" not in st.get_user_settings("bob", "dashboard")
    # unknown namespace/user -> empty, never invented
    assert st.get_user_settings("alice", "preferences") == {}
    assert st.get_user_settings("nobody", "dashboard") == {}


def test_settings_survive_store_reopen(tmp_path):
    path = tmp_path / "hub.db"
    st = SqliteStore(path)
    st.create_user("alice", "password-a1")
    st.set_user_settings("alice", "settings-center", {"appearance": {"theme": "dark"}})
    st.close()
    st2 = SqliteStore(path)   # "next login"
    assert st2.get_user_settings("alice", "settings-center")["appearance"]["theme"] == "dark"


def test_reset_is_explicit_and_scoped(tmp_path):
    st = SqliteStore(tmp_path / "hub.db")
    st.create_user("alice", "password-a1")
    st.set_user_settings("alice", "dashboard", {"a": 1})
    st.set_user_settings("alice", "preferences", {"tz": "UTC"})
    st.delete_user_settings("alice", "dashboard")          # Reset Dashboard
    assert st.get_user_settings("alice", "dashboard") == {}
    assert st.get_user_settings("alice", "preferences") == {"tz": "UTC"}
    st.delete_user_settings("alice")                        # Factory Reset
    assert st.get_user_settings("alice", "preferences") == {}


# ─────────────────────────────── HTTP layer ───────────────────────────────
@pytest.fixture()
def client():
    import app as app_module
    return TestClient(app_module.app)


def _login(client) -> None:
    # the app seeds its first admin from config (admin/admin in tests)
    r = client.post("/login", data={"username": "admin", "password": "admin"},
                    follow_redirects=False)
    assert r.status_code in (200, 302, 303)


def test_endpoints_require_session(client):
    assert client.get("/user/settings").status_code == 401
    assert client.post("/user/settings", json={"ns": "dashboard", "data": {}}).status_code == 401
    assert client.delete("/user/settings").status_code == 401


def test_endpoints_roundtrip_and_validation(client):
    _login(client)
    r = client.post("/user/settings", json={"ns": "dashboard", "data": {"chartTf": "5m"}})
    assert r.status_code == 200 and r.json()["saved"]
    r = client.get("/user/settings", params={"ns": "dashboard"})
    assert r.json()["data"] == {"chartTf": "5m"}
    # unknown namespace and non-object payloads are rejected
    assert client.get("/user/settings", params={"ns": "evil"}).status_code == 400
    assert client.post("/user/settings", json={"ns": "dashboard", "data": [1]}).status_code == 400
    # explicit reset clears it
    assert client.delete("/user/settings", params={"ns": "dashboard"}).status_code == 200
    assert client.get("/user/settings", params={"ns": "dashboard"}).json()["data"] == {}


# ───────────────────────── engine watchlist persistence ─────────────────────
def test_engine_symbols_roundtrip_through_overrides(tmp_path):
    from services.runtime_settings import save_overrides, load_overrides
    p = str(tmp_path / "rs.json")
    save_overrides(p, {"engine_symbols": "BTCUSDT,DOGEUSDT"})
    got = load_overrides(p)
    assert got["engine_symbols"] == "BTCUSDT,DOGEUSDT"


def test_market_symbols_endpoint_persists(client, monkeypatch):
    import webhook_api as _wa
    saved = {}
    monkeypatch.setattr(_wa, "save_overrides", lambda path, snap: saved.update(snap))
    r = client.post("/market/symbols", json={"symbols": ["btcusdt", "ethusdt"]},
                    headers={"X-Webhook-Secret": _wa.settings.webhook_secret})
    assert r.status_code == 200
    assert saved.get("engine_symbols") == "BTCUSDT,ETHUSDT"
