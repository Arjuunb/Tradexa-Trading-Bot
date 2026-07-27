"""Strategy versioning & collaboration.

Two contracts:
  * the change log is DERIVED from stored snapshots, so it cannot describe a
    change that did not happen, or miss one that did;
  * comments belong to their authors and share grants belong to the owner —
    neither can be rewritten by the other party.
"""
import pytest

from services import strategy_collab as sc

V1 = {
    "name": "EMA Trend", "symbol": "BTCUSDT", "timeframe": "4h", "side": "long",
    "entry": {"op": "AND", "rules": [
        {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"},
        {"type": "rsi", "period": 14, "value": 55, "op": "above"},
    ]},
    "stop": {"type": "atr", "mult": 1.5, "period": 14},
    "target": {"type": "rr", "rr": 2}, "risk_per_trade_pct": 0.01,
}


@pytest.fixture()
def store(tmp_path):
    return sc.CollabStore(str(tmp_path / "collab.json"))


# ----------------------------------------------------------------- diffing

def test_a_parameter_edit_reads_as_a_change_not_an_add_and_a_remove():
    """The whole point of keying rules by type: RSI 55 -> 60 is ONE change."""
    v2 = {**V1, "entry": {"op": "AND", "rules": [
        {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"},
        {"type": "rsi", "period": 14, "value": 60, "op": "above"},
    ]}}
    d = sc.diff_specs(V1, v2)
    assert d["changed"] is True
    assert len(d["rules"]) == 1
    r = d["rules"][0]
    assert r["kind"] == "changed" and r["rule_type"] == "rsi"
    assert "55" in r["text"] and "60" in r["text"]


def test_added_and_removed_rules_are_reported_as_such():
    v2 = {**V1, "entry": {"op": "AND", "rules": [
        {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"},
        {"type": "volume_spike", "mult": 2.0},
    ]}}
    kinds = {r["kind"]: r["rule_type"] for r in sc.diff_specs(V1, v2)["rules"]}
    assert kinds["removed"] == "rsi"
    assert kinds["added"] == "volume_spike"


def test_stop_target_and_risk_changes_are_captured():
    v2 = {**V1, "stop": {"type": "atr", "mult": 2.5, "period": 14},
          "risk_per_trade_pct": 0.005}
    fields = {f["field"]: (f["before"], f["after"]) for f in sc.diff_specs(V1, v2)["fields"]}
    assert fields["stop.mult"] == (1.5, 2.5)
    assert fields["risk_per_trade_pct"] == (0.01, 0.005)


def test_library_metadata_is_not_a_strategy_change():
    """Favouriting or tagging a strategy must never show up as an edit."""
    v2 = {**V1, "favorite": True, "tags": ["btc"], "folder": "Live",
          "updated_at": "2026-01-01", "versions": [{"v": 1}]}
    assert sc.diff_specs(V1, v2)["changed"] is False


def test_identical_specs_say_so_rather_than_inventing_a_line():
    d = sc.diff_specs(V1, dict(V1))
    assert d["changed"] is False
    assert d["summary"] == ["No changes to the strategy definition."]


def test_diff_tolerates_a_missing_side():
    assert sc.diff_specs(None, V1)["changed"] is True
    assert sc.diff_specs(V1, None)["changed"] is True
    assert sc.diff_specs(None, None)["changed"] is False


# --------------------------------------------------------------- change log

def test_changelog_describes_each_recorded_edit():
    current = {**V1, "risk_per_trade_pct": 0.02,
               "versions": [
                   {"v": 1, "at": "2026-01-01", "name": "EMA Trend", "spec": V1},
                   {"v": 2, "at": "2026-02-01", "name": "EMA Trend",
                    "spec": {**V1, "stop": {"type": "atr", "mult": 2.0, "period": 14}}},
               ]}
    log = sc.changelog(current)
    assert log["available"] is True
    assert [e["v"] for e in log["entries"]] == [1, 2, "current"]
    assert log["entries"][0]["changes"] == ["Initial recorded version."]
    assert any("stop.mult" in c for c in log["entries"][1]["changes"])
    assert any("risk_per_trade_pct" in c for c in log["entries"][2]["changes"])


def test_changelog_needs_no_authored_notes():
    """A team that never wrote a commit message still gets an accurate log."""
    current = {**V1, "target": {"type": "rr", "rr": 3},
               "versions": [{"v": 1, "at": "2026-01-01", "spec": V1}]}
    changes = sc.changelog(current)["entries"][-1]["changes"]
    assert any("target.rr" in c and "3" in c for c in changes)


def test_a_never_edited_strategy_says_so(store):
    log = sc.changelog({**V1, "versions": []})
    assert log["available"] is True and log["entries"] == []
    assert "only ever been saved once" in log["note"]


def test_changelog_of_a_missing_strategy_is_unavailable():
    assert sc.changelog(None)["available"] is False


# ---------------------------------------------------------------- comments

def test_comment_round_trip(store):
    c = store.add_comment("s1", author="alice", body="Why RSI 55?")
    assert c["author"] == "alice" and c["edited_at"] is None
    assert [x["body"] for x in store.comments("s1")] == ["Why RSI 55?"]


def test_comments_can_be_anchored_to_a_version(store):
    store.add_comment("s1", author="alice", body="on v1", version=1)
    store.add_comment("s1", author="bob", body="on v2", version=2)
    assert [c["body"] for c in store.comments("s1", version=1)] == ["on v1"]


def test_replies_must_point_at_a_real_comment(store):
    c = store.add_comment("s1", author="alice", body="root")
    assert store.add_comment("s1", author="bob", body="reply",
                             reply_to=c["id"])["reply_to"] == c["id"]
    assert "error" in store.add_comment("s1", author="bob", body="x", reply_to="nope")


def test_an_empty_comment_is_rejected(store):
    assert "error" in store.add_comment("s1", author="alice", body="   ")


def test_only_the_author_edits_their_own_comment(store):
    c = store.add_comment("s1", author="alice", body="first")
    assert "error" in store.edit_comment("s1", c["id"], author="bob", body="hijacked")
    out = store.edit_comment("s1", c["id"], author="alice", body="second")
    assert out["body"] == "second" and out["edited_at"]


def test_an_edit_is_stamped_so_it_cannot_pass_as_the_original(store):
    c = store.add_comment("s1", author="alice", body="first")
    assert store.edit_comment("s1", c["id"], author="alice", body="x")["edited_at"] is not None


def test_only_the_author_deletes_their_own_comment(store):
    c = store.add_comment("s1", author="alice", body="mine")
    assert store.delete_comment("s1", c["id"], author="bob") is False
    assert store.delete_comment("s1", c["id"], author="alice") is True
    assert store.comments("s1") == []


def test_deleting_a_comment_with_replies_keeps_the_thread_readable(store):
    root = store.add_comment("s1", author="alice", body="root")
    store.add_comment("s1", author="bob", body="reply", reply_to=root["id"])
    store.delete_comment("s1", root["id"], author="alice")
    rows = store.comments("s1")
    assert len(rows) == 2, "the reply must not be orphaned"
    assert rows[0]["body"] == "[deleted]" and rows[0]["deleted"] is True


def test_editing_a_missing_comment_is_none(store):
    assert store.edit_comment("s1", "nope", author="alice", body="x") is None


# ------------------------------------------------------------- permissions

def test_share_roles_are_ordered_and_default_deny():
    assert sc.share_can("editor", "comment") is True
    assert sc.share_can("commenter", "edit") is False
    assert sc.share_can("viewer", "comment") is False
    assert sc.share_can(None, "view") is False
    assert sc.share_can("admin", "view") is False, "account roles are not share roles"
    assert sc.share_can("editor", "nonsense") is False


def test_owner_can_grant_and_revoke(store):
    out = store.share("s1", owner="alice", user="bob", role="editor")
    assert out["grants"]["bob"]["role"] == "editor"
    assert store.role_for("s1", "bob") == "editor"
    store.unshare("s1", owner="alice", user="bob")
    assert store.role_for("s1", "bob") is None


def test_a_non_owner_cannot_grant_themselves_access(store):
    store.share("s1", owner="alice", user="bob", role="viewer")
    assert "error" in store.share("s1", owner="bob", user="bob", role="editor")
    assert "error" in store.unshare("s1", owner="bob", user="bob")
    assert store.role_for("s1", "bob") == "viewer"


def test_ownership_cannot_be_granted_away(store):
    store.share("s1", owner="alice", user="bob", role="editor")
    assert "error" in store.share("s1", owner="alice", user="bob", role="owner")
    assert store.role_for("s1", "alice") == "owner"


def test_an_account_role_cannot_be_used_as_a_share_role(store):
    """rbac's roles (admin/operator) are a different axis — accepting one here
    would silently hand out privileges nobody chose to share."""
    for role in ("admin", "operator", "owner"):
        assert "error" in store.share("s1", owner="alice", user="bob", role=role)


def test_the_owner_can_do_everything_without_an_explicit_grant(store):
    store.share("s1", owner="alice", user="bob", role="viewer")
    for cap in ("view", "comment", "edit", "restore"):
        assert store.can("s1", "alice", cap) is True


def test_capabilities_follow_the_granted_role(store):
    store.share("s1", owner="alice", user="bob", role="commenter")
    assert store.can("s1", "bob", "view") is True
    assert store.can("s1", "bob", "comment") is True
    assert store.can("s1", "bob", "edit") is False


def test_an_unshared_strategy_grants_nobody_anything(store):
    assert store.role_for("s1", "carol") is None
    assert store.can("s1", "carol", "view") is False


def test_shares_survive_a_reopen(store):
    store.share("s1", owner="alice", user="bob", role="editor")
    store.add_comment("s1", author="bob", body="looks good")
    reopened = sc.CollabStore(str(store.path))
    assert reopened.role_for("s1", "bob") == "editor"
    assert len(reopened.comments("s1")) == 1


def test_a_corrupt_store_file_reads_as_empty(tmp_path):
    p = tmp_path / "collab.json"
    p.write_text("{not json")
    s = sc.CollabStore(str(p))
    assert s.comments("s1") == [] and s.shares("s1")["owner"] is None


# ---------------------------------------------------------------- endpoints

@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    from services.custom_store import CustomStore
    monkeypatch.setattr(webhook_api, "collab_store",
                        sc.CollabStore(str(tmp_path / "collab.json")))
    monkeypatch.setattr(webhook_api, "custom_store",
                        CustomStore(str(tmp_path / "custom.json")))
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def _secret():
    from config import settings
    return {"X-Webhook-Secret": settings.webhook_secret}


@pytest.fixture()
def saved(client):
    """A strategy with a real edit behind it, so the changelog has something."""
    import webhook_api
    s = webhook_api.custom_store.save(dict(V1))
    webhook_api.custom_store.save({**s, "risk_per_trade_pct": 0.02})
    return s["id"]


def test_changelog_endpoint_describes_the_real_edit(client, saved):
    j = client.get(f"/strategy/custom/{saved}/changelog").json()
    assert j["available"] is True and j["versions"] == 1
    assert any("risk_per_trade_pct" in c
               for e in j["entries"] for c in e["changes"])


def test_changelog_of_a_missing_strategy_is_404(client):
    assert client.get("/strategy/custom/nope/changelog").status_code == 404


def test_compare_endpoint_diffs_two_versions(client, saved):
    j = client.get(f"/strategy/custom/{saved}/compare?a=1&b=current").json()
    assert j["diff"]["changed"] is True


def test_compare_rejects_a_version_that_does_not_exist(client, saved):
    assert client.get(f"/strategy/custom/{saved}/compare?a=99").status_code == 404


def test_comment_endpoints_round_trip(client, saved):
    r = client.post(f"/strategy/custom/{saved}/comments",
                    json={"body": "Why 55?", "version": 1}, headers=_secret())
    assert r.status_code == 200
    cid = r.json()["id"]
    assert len(client.get(f"/strategy/custom/{saved}/comments").json()["comments"]) == 1

    e = client.patch(f"/strategy/custom/{saved}/comments/{cid}",
                     json={"body": "Why RSI 55?"}, headers=_secret())
    assert e.status_code == 200 and e.json()["edited_at"]

    d = client.delete(f"/strategy/custom/{saved}/comments/{cid}", headers=_secret())
    assert d.status_code == 200
    assert client.get(f"/strategy/custom/{saved}/comments").json()["comments"] == []


def test_an_empty_comment_is_a_400(client, saved):
    assert client.post(f"/strategy/custom/{saved}/comments", json={"body": " "},
                       headers=_secret()).status_code == 400


def test_commenting_requires_the_control_credential(client, saved):
    assert client.post(f"/strategy/custom/{saved}/comments",
                       json={"body": "hi"}).status_code == 401


def test_share_endpoint_grants_and_revokes(client, saved):
    r = client.post(f"/strategy/custom/{saved}/share",
                    json={"user": "bob", "role": "editor"}, headers=_secret())
    assert r.status_code == 200 and r.json()["grants"]["bob"]["role"] == "editor"

    s = client.get(f"/strategy/custom/{saved}/shares").json()
    assert s["my_role"] == "owner" and s["roles"] == list(sc.SHARE_ROLES)

    r = client.post(f"/strategy/custom/{saved}/share",
                    json={"user": "bob", "revoke": True}, headers=_secret())
    assert r.json()["grants"] == {}


def test_share_endpoint_refuses_an_account_role(client, saved):
    r = client.post(f"/strategy/custom/{saved}/share",
                    json={"user": "bob", "role": "admin"}, headers=_secret())
    assert r.status_code == 400


def test_share_endpoint_requires_a_user(client, saved):
    assert client.post(f"/strategy/custom/{saved}/share", json={},
                       headers=_secret()).status_code == 400
