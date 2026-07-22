"""Phase C-2: tenant-scope the strategy library (custom_store).

Verifies that scoping the JSON strategy store by ``tenant_id`` keeps single-owner
behaviour identical (default tenant, legacy records read as the owner's) while
isolating tenants from one another once a tenant is passed.
"""
from services.custom_store import CustomStore
from services.tenancy import OWNER_TENANT


def _store(tmp_path):
    return CustomStore(str(tmp_path / "custom.json"))


# ---------------------------------------------------------------- owner default
def test_single_owner_roundtrip_unchanged(tmp_path):
    cs = _store(tmp_path)
    saved = cs.save({"name": "Momentum", "side": "long"})   # no tenant -> owner
    sid = saved["id"]
    assert saved["tenant_id"] == OWNER_TENANT
    assert cs.get(sid)["name"] == "Momentum"
    assert [s["id"] for s in cs.list()] == [sid]
    assert cs.set_favorite(sid, True)["favorite"] is True
    assert cs.set_tags(sid, ["a", "b"])["tags"] == ["a", "b"]
    assert cs.set_meta(sid, name="Renamed", folder="Ideas")["name"] == "Renamed"
    dup = cs.duplicate(sid)
    assert dup["tenant_id"] == OWNER_TENANT and dup["name"].endswith("(copy)")
    assert cs.delete(sid) is True
    assert cs.get(sid) is None


# ---------------------------------------------------------------- legacy records
def test_legacy_record_without_tenant_reads_as_owner(tmp_path):
    cs = _store(tmp_path)
    # simulate a pre-C-2 record on disk (no tenant_id field)
    cs._write({"x1": {"id": "x1", "name": "Legacy", "updated_at": "t"}})
    assert cs.get("x1")["name"] == "Legacy"                 # owner sees it
    assert [s["id"] for s in cs.list()] == ["x1"]
    assert cs.get("x1", tenant="alice") is None             # a tenant does not


# ---------------------------------------------------------------- isolation
def test_tenants_are_isolated(tmp_path):
    cs = _store(tmp_path)
    a = cs.save({"name": "A-strat"}, tenant="alice")
    b = cs.save({"name": "B-strat"}, tenant="bob")

    assert [s["id"] for s in cs.list(tenant="alice")] == [a["id"]]
    assert [s["id"] for s in cs.list(tenant="bob")] == [b["id"]]
    assert cs.list(tenant=OWNER_TENANT) == []

    # cross-tenant reads/writes are invisible
    assert cs.get(a["id"], tenant="bob") is None
    assert cs.set_favorite(a["id"], True, tenant="bob") is None
    assert cs.set_tags(a["id"], ["x"], tenant="bob") is None
    assert cs.set_meta(a["id"], name="hijack", tenant="bob") is None
    assert cs.duplicate(a["id"], tenant="bob") is None
    assert cs.history(a["id"], tenant="bob") is None
    assert cs.delete(a["id"], tenant="bob") is False
    assert cs.get(a["id"], tenant="alice")["name"] == "A-strat"  # untouched


def test_versioning_and_restore_are_tenant_scoped(tmp_path):
    cs = _store(tmp_path)
    v1 = cs.save({"name": "S", "side": "long"}, tenant="alice")
    sid = v1["id"]
    cs.save({"id": sid, "name": "S", "side": "short"}, tenant="alice")  # definition changed
    hist = cs.history(sid, tenant="alice")
    assert len(hist) == 1 and hist[0]["spec"]["side"] == "long"
    # bob cannot see or restore alice's history
    assert cs.history(sid, tenant="bob") is None
    assert cs.restore(sid, 1, tenant="bob") is None
    restored = cs.restore(sid, 1, tenant="alice")
    assert restored["side"] == "long" and restored["tenant_id"] == "alice"


def test_same_sid_across_tenants_never_collides(tmp_path):
    cs = _store(tmp_path)
    cs.save({"id": "shared", "name": "alice-owns"}, tenant="alice")
    # bob saving the same explicit id must not overwrite alice's record: the store
    # mints a fresh sid for bob so both survive independently.
    bob = cs.save({"id": "shared", "name": "bob-tried"}, tenant="bob")
    assert bob["id"] != "shared" and bob["tenant_id"] == "bob"
    assert cs.get("shared", tenant="alice")["name"] == "alice-owns"
    assert cs.get(bob["id"], tenant="bob")["name"] == "bob-tried"
