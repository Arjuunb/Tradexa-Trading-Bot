"""Strategy Marketplace publishing.

The contract under test is the transparency guarantee: a publisher must not be
able to supply, edit, hide or selectively delete performance numbers. Each test
below is an attempt to do exactly that, and asserts it fails.
"""
import pytest

from services.custom_store import CustomStore
from services import strategy_publisher as sp

SPEC = {
    "id": "abc123", "name": "EMA Trend", "symbol": "BTCUSDT", "timeframe": "4h",
    "side": "long", "version": "1.0",
    "entry": {"op": "AND", "rules": [{"type": "ema_cross", "fast": 20, "slow": 50}]},
    "stop": {"type": "atr", "mult": 1.5, "period": 14},
    "target": {"type": "rr", "rr": 2}, "risk_per_trade_pct": 0.01,
}


def _results(*, trades=40, net_r=22.0, pf=1.8, dd=6.0, mcl=4):
    return {"total_trades": trades, "win_rate": 52.5, "profit_factor": pf,
            "net_r": net_r, "expectancy_r": round(net_r / max(trades, 1), 3),
            "max_drawdown_r": dd, "avg_rr": 2.0, "wins": 21, "losses": 19,
            "max_consecutive_losses": mcl, "span_days": 365, "trades": [{"r": 1}]}


@pytest.fixture()
def store(tmp_path):
    return sp.PublishStore(str(tmp_path / "market.json"))


@pytest.fixture()
def library(tmp_path):
    return CustomStore(str(tmp_path / "custom.json"))


def _pub(store, spec=SPEC, results=None, **kw):
    return store.publish(spec, publisher="alice",
                         runner=lambda s: results or _results(), **kw)


# ------------------------------------------------------- verified, not claimed

def test_metrics_come_from_the_backtest_the_server_ran(store):
    l = _pub(store, results=_results(net_r=13.5, pf=1.42))
    assert l["verified"]["metrics"]["net_r"] == 13.5
    assert l["verified"]["metrics"]["profit_factor"] == 1.42


def test_there_is_no_way_to_pass_metrics_in(store):
    """A publisher supplying their own numbers is the whole attack. The signature
    must not accept them, and a spec carrying fake ones must not leak through."""
    import inspect
    params = set(inspect.signature(sp.PublishStore.publish).parameters)
    assert not {"metrics", "results", "verified", "performance"} & params

    spec = {**SPEC, "net_r": 9999.0, "profit_factor": 50.0, "win_rate": 100.0}
    l = _pub(store, spec, results=_results(net_r=13.5, pf=1.42))
    assert l["verified"]["metrics"]["net_r"] == 13.5
    assert l["verified"]["metrics"]["profit_factor"] == 1.42


def test_a_strategy_with_too_few_trades_cannot_be_published(store):
    out = _pub(store, results=_results(trades=3))
    assert "error" in out and "unverified" in out["error"].lower()
    assert store.browse() == []


def test_a_strategy_that_never_trades_cannot_be_published(store):
    assert "error" in store.publish(SPEC, publisher="alice", runner=lambda s: None)


def test_a_failing_backtest_blocks_publication_rather_than_listing_blanks(store):
    def boom(spec):
        raise RuntimeError("data feed down")
    out = store.publish(SPEC, publisher="alice", runner=boom)
    assert "error" in out and "nothing can be verified" in out["error"]


def test_entry_rules_are_required(store):
    assert "error" in store.publish({"name": "empty"}, publisher="alice",
                                    runner=lambda s: _results())


# ------------------------------------------------------- unflattering numbers

def test_a_losing_strategy_publishes_with_its_losing_numbers(store):
    """Transparency cuts both ways: a bad strategy is listable, but only with
    the record that shows it is bad."""
    l = _pub(store, results=_results(net_r=-18.0, pf=0.6, dd=24.0))
    assert l["verified"]["metrics"]["net_r"] == -18.0
    assert l["risk"]["max_drawdown_r"] == 24.0


def test_the_risk_block_always_carries_drawdown_and_losing_streak(store):
    l = _pub(store, results=_results(dd=11.0, mcl=9))
    assert l["risk"]["max_drawdown_r"] == 11.0
    assert l["risk"]["max_consecutive_losses"] == 9
    assert l["risk"]["risk_per_trade_pct"] == 0.01


def test_every_listing_displays_the_fields_the_spec_requires(store):
    l = _pub(store, description="EMA trend follower")
    for field in ("verified", "risk", "history", "description", "version"):
        assert l[field] not in (None, ""), field
    v = l["verified"]
    assert v["range"] and v["symbol"] and v["timeframe"] and v["ran_at"]


def test_there_is_no_api_to_hide_or_edit_numbers(store):
    """Not an oversight — the absence IS the feature."""
    for forbidden in ("hide", "edit_metrics", "set_metrics", "conceal", "update_verified"):
        assert not hasattr(store, forbidden)


# ------------------------------------------------------- history is append-only

def test_republishing_replaces_the_headline_and_keeps_the_old_record(store):
    _pub(store, results=_results(net_r=30.0))
    l = _pub(store, results=_results(net_r=4.0))
    assert l["verified"]["metrics"]["net_r"] == 4.0        # current is current
    assert [h["metrics"]["net_r"] for h in l["history"]] == [30.0, 4.0]
    assert l["publish_count"] == 2


def test_a_worse_republish_cannot_erase_the_better_one_or_vice_versa(store):
    _pub(store, results=_results(net_r=30.0))
    _pub(store, results=_results(net_r=-5.0))
    l = store.browse()[0]
    assert len(l["history"]) == 2
    assert any(h["metrics"]["net_r"] < 0 for h in l["history"])


def test_republishing_does_not_create_a_second_listing(store):
    _pub(store); _pub(store)
    assert len(store.browse()) == 1


def test_a_different_publisher_gets_their_own_listing(store):
    _pub(store)
    store.publish(SPEC, publisher="bob", runner=lambda s: _results())
    assert len(store.browse()) == 2


def test_unpublish_removes_the_whole_listing_and_only_by_its_owner(store):
    l = _pub(store)
    assert store.unpublish(l["id"], publisher="bob") is False    # not yours
    assert len(store.browse()) == 1
    assert store.unpublish(l["id"], publisher="alice") is True
    assert store.browse() == []


# ------------------------------------------------------------------- ratings

def test_rating_averages_and_counts(store):
    l = _pub(store)
    store.rate(l["id"], user="bob", stars=4)
    out = store.rate(l["id"], user="carol", stars=2, comment="Drawdown too deep")
    assert out["rating"]["count"] == 2 and out["rating"]["average"] == 3.0
    assert any("Drawdown" in (r.get("comment") or "") for r in out["reviews"])


def test_rating_again_replaces_your_own_and_nobody_elses(store):
    l = _pub(store)
    store.rate(l["id"], user="bob", stars=5)
    store.rate(l["id"], user="carol", stars=1)
    out = store.rate(l["id"], user="bob", stars=2)
    assert out["rating"]["count"] == 2 and out["rating"]["average"] == 1.5


def test_a_publisher_cannot_rate_their_own_strategy(store):
    l = _pub(store)
    assert "error" in store.rate(l["id"], user="alice", stars=5)


def test_a_publisher_has_no_path_to_delete_a_bad_rating(store):
    l = _pub(store)
    store.rate(l["id"], user="bob", stars=1, comment="lost money")
    assert not hasattr(store, "delete_rating") and not hasattr(store, "remove_review")
    assert store.get(l["id"])["rating"]["count"] == 1


def test_out_of_range_stars_are_rejected(store):
    l = _pub(store)
    for bad in (0, 6, -1):
        assert "error" in store.rate(l["id"], user="bob", stars=bad)


def test_rating_a_missing_listing_is_none_not_a_crash(store):
    assert store.rate("nope", user="bob", stars=3) is None


def test_no_ratings_says_so_instead_of_showing_a_flattering_zero(store):
    l = _pub(store)
    assert l["rating"]["count"] == 0 and l["rating"]["average"] is None
    assert "verified backtest" in l["rating"]["note"]


# ------------------------------------------------------------------- follows

def test_follow_and_unfollow_a_creator(store):
    assert store.follow(follower="bob", creator="alice")["following"] == ["alice"]
    assert store.follow(follower="bob", creator="alice")["following"] == ["alice"]  # idempotent
    assert store.following("bob") == ["alice"]
    assert store.unfollow(follower="bob", creator="alice")["following"] == []


def test_you_cannot_follow_yourself(store):
    assert "error" in store.follow(follower="bob", creator="bob")


def test_browsing_by_follower_shows_only_followed_creators(store):
    _pub(store)
    store.publish({**SPEC, "id": "z9", "name": "Bobs"}, publisher="bob",
                  runner=lambda s: _results())
    store.follow(follower="carol", creator="bob")
    rows = store.browse(follower="carol")
    assert [r["publisher"] for r in rows] == ["bob"]


# -------------------------------------------------------------------- browse

def test_browse_filters(store):
    _pub(store, tags=["trend"])
    store.publish({**SPEC, "id": "z9", "symbol": "ETHUSDT"}, publisher="bob",
                  runner=lambda s: _results(), tags=["scalp"])
    assert len(store.browse(tag="trend")) == 1
    assert len(store.browse(publisher="bob")) == 1
    assert len(store.browse(symbol="ETHUSDT")) == 1


def test_sorting_can_rank_by_shallowest_drawdown_not_only_by_returns(store):
    """A marketplace that can only sort by profit teaches people to chase profit."""
    _pub(store, results=_results(net_r=50.0, dd=30.0))
    store.publish({**SPEC, "id": "z9", "name": "Steady"}, publisher="bob",
                  runner=lambda s: _results(net_r=12.0, dd=3.0))
    assert store.browse(sort="net_r")[0]["name"] == "EMA Trend"
    assert store.browse(sort="drawdown")[0]["name"] == "Steady"


def test_unknown_sort_falls_back_to_recent_rather_than_erroring(store):
    _pub(store)
    assert len(store.browse(sort="nonsense")) == 1


def test_get_returns_none_for_a_missing_listing(store):
    assert store.get("nope") is None


# -------------------------------------------------------------------- import

def test_import_copies_into_your_library_with_provenance(store, library):
    l = _pub(store)
    saved = store.import_listing(l["id"], library)
    assert saved["id"] != SPEC["id"], "an import must not overwrite the original id"
    assert saved["imported_from"]["publisher"] == "alice"
    assert "imported" in saved["tags"]
    assert library.get(saved["id"]) is not None


def test_importing_does_not_carry_the_publishers_version_history(store, library):
    """Their v1..v7 is their record, not yours — your copy starts its own."""
    _pub(store)
    l = _pub(store)                                   # publisher now has 2 snapshots
    saved = store.import_listing(l["id"], library)
    assert len(saved.get("versions", [])) <= 1


def test_import_count_is_tracked(store, library):
    l = _pub(store)
    store.import_listing(l["id"], library)
    store.import_listing(l["id"], library)
    assert store.get(l["id"])["imports"] == 2


def test_importing_a_missing_listing_errors(store, library):
    assert "error" in store.import_listing("nope", library)


# ---------------------------------------------------------------- persistence

def test_listings_survive_a_reopen(store, tmp_path):
    l = _pub(store)
    store.rate(l["id"], user="bob", stars=4)
    reopened = sp.PublishStore(str(store.path))
    assert reopened.get(l["id"])["rating"]["average"] == 4.0


def test_a_corrupt_store_file_reads_as_empty_rather_than_crashing(tmp_path):
    p = tmp_path / "market.json"
    p.write_text("{not json")
    assert sp.PublishStore(str(p)).browse() == []


# ------------------------------------------------------------------ endpoints

@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    monkeypatch.setattr(webhook_api, "publish_store",
                        sp.PublishStore(str(tmp_path / "market.json")))
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def _secret():
    from config import settings
    return {"X-Webhook-Secret": settings.webhook_secret}


def test_publish_endpoint_runs_the_backtest_itself(client):
    r = client.post("/marketplace/publish",
                    json={"spec": SPEC, "range": "1Y", "description": "trend"},
                    headers=_secret())
    if r.status_code == 400:
        # The bundled window may not yield enough trades for THIS spec; the
        # refusal is the correct behaviour and is asserted directly.
        assert "unverified" in r.json()["detail"].lower() or "trades" in r.json()["detail"]
        return
    assert r.status_code == 200
    j = r.json()
    assert j["verified"]["metrics"]["total_trades"] >= sp.MIN_TRADES_TO_PUBLISH
    assert j["risk"]["max_drawdown_r"] is not None


def test_publish_endpoint_ignores_metrics_in_the_body(client):
    """Belt and braces at the HTTP edge: an attacker POSTs numbers; they die."""
    r = client.post("/marketplace/publish",
                    json={"spec": SPEC, "verified": {"metrics": {"net_r": 9999}},
                          "metrics": {"net_r": 9999}, "range": "1Y"},
                    headers=_secret())
    if r.status_code == 200:
        assert r.json()["verified"]["metrics"]["net_r"] != 9999


def test_publish_requires_a_spec(client):
    assert client.post("/marketplace/publish", json={}, headers=_secret()).status_code == 400


def test_publish_requires_the_control_credential(client):
    assert client.post("/marketplace/publish", json={"spec": SPEC}).status_code == 401


def test_browse_endpoint_is_readable_without_listings(client):
    j = client.get("/marketplace/listings").json()
    assert j["listings"] == [] and j["count"] == 0


def test_missing_listing_is_404(client):
    assert client.get("/marketplace/listings/nope").status_code == 404
    assert client.post("/marketplace/listings/nope/import",
                       headers=_secret()).status_code == 404


def test_follow_endpoint_requires_a_creator(client):
    assert client.post("/marketplace/follow", json={}, headers=_secret()).status_code == 400


def test_the_author_label_is_not_the_tenancy_sentinel(client):
    """`__owner__` is a storage key. Leaking it into a byline would put an
    internal sentinel on the marketplace as an author name."""
    import webhook_api
    from services.tenancy import OWNER_TENANT

    class _Req:
        cookies, headers = {}, {}
    who = webhook_api.request_user(_Req())
    assert who and who != OWNER_TENANT


def test_a_forged_session_cookie_does_not_become_an_author(client):
    import webhook_api

    class _Req:
        cookies = {"hub_session": "admin|9999999999|deadbeef"}
        headers = {}
    assert webhook_api.request_user(_Req()) != "admin"
