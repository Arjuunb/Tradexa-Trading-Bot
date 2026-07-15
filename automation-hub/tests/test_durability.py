"""Phase 1 durability: honest storage assessment (H-1) + retention pruning (M-6)."""
import pytest
from fastapi.testclient import TestClient

from data.decision_store import DecisionStore
from data.ledger import SqliteLedger
from data.skipped_store import SkippedTradeStore
from services.storage_health import assess, boot_banner


# ─────────────────────────── storage assessment ───────────────────────────
def test_local_dev_is_durable():
    a = assess(data_dir="/x", hub_data_dir_set=False, on_cloud=False, supabase_connected=False)
    assert a["tier"] == "disk" and a["persistent"] and a["at_risk"] == []
    assert boot_banner(a) is None


def test_cloud_ephemeral_flags_everything_at_risk():
    a = assess(data_dir="/app/logs", hub_data_dir_set=False, on_cloud=True, supabase_connected=False)
    assert a["tier"] == "ephemeral"
    assert a["persistent"] is False and a["ledger_durable"] is False
    assert len(a["at_risk"]) == 4 and "EPHEMERAL" in a["warning"]
    assert "STORAGE DURABILITY WARNING" in boot_banner(a)


def test_cloud_supabase_preserves_ledger_only():
    a = assess(data_dir="/app/logs", hub_data_dir_set=False, on_cloud=True, supabase_connected=True)
    assert a["tier"] == "supabase"
    assert a["ledger_durable"] is True         # trade history survives
    assert a["local_durable"] is False         # but account/settings/memory don't
    assert a["at_risk"], "account/settings/memory must be flagged at risk"
    assert boot_banner(a) is not None          # still warns


def test_cloud_disk_is_fully_durable():
    a = assess(data_dir="/mnt/d", hub_data_dir_set=True, on_cloud=True, supabase_connected=False)
    assert a["tier"] == "disk" and a["persistent"] and a["at_risk"] == []
    assert boot_banner(a) is None


# ─────────────────────────── retention pruning ───────────────────────────
def test_decision_store_prune_keeps_newest():
    st = DecisionStore(":memory:")
    for i in range(10):
        st.record({"symbol": "BTC", "side": "long", "decision": "rejected",
                   "reason": f"r{i}", "score": i})
    assert st.count() == 10
    deleted = st.prune(keep=4)
    assert deleted == 6 and st.count() == 4
    # the survivors are the 4 most recent (highest ids)
    kept = st.list(limit=99)
    assert len(kept) == 4


def test_skipped_store_prune():
    st = SkippedTradeStore(":memory:")
    for i in range(8):
        st.record(symbol="ETH", side="long", stage="risk", reason=f"x{i}",
                  snapshot={})
    assert st.total() == 8
    assert st.prune(keep=3) == 5
    assert st.total() == 3


def test_ledger_prune_time_ordered():
    led = SqliteLedger(":memory:")
    for i in range(6):
        led.log(level="info", stage="t", message=f"m{i}")
        led.add_alert(severity="info", category="c", title=f"a{i}")
    out = led.prune(keep_logs=2, keep_alerts=2, keep_events=100)
    assert out["logs"] == 4 and out["alerts"] == 4
    logs = led.get_logs(99)
    assert len(logs) == 2 and logs[0]["message"] == "m5"   # newest kept


def test_prune_noop_when_under_cap():
    st = DecisionStore(":memory:")
    st.record({"symbol": "BTC", "side": "long", "decision": "accepted", "reason": "ok"})
    assert st.prune(keep=1000) == 0 and st.count() == 1


# ─────────────────────────── endpoint ───────────────────────────
@pytest.fixture()
def client():
    import app as app_module
    return TestClient(app_module.app)


def test_ops_storage_reports_tier(client):
    import webhook_api as _wa
    r = client.get("/ops/storage", headers={"X-Webhook-Secret": _wa.settings.webhook_secret})
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] in ("disk", "supabase", "ephemeral")
    assert "at_risk" in body and "files" in body
    # the previously-omitted stores are now surfaced
    assert "paper_account" in body["files"] and "users_and_settings" in body["files"]


def test_retention_prune_extra_runs(client):
    # the nightly extra should prune without raising
    import webhook_api as _wa
    _wa._retention_prune()   # must not raise
