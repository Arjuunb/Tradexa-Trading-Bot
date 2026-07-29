"""The adapter between live account state and the Portfolio Engine.

The engine's own tests prove the mathematics. These prove the translation: that
the paper account is described accurately, that a broker the platform cannot
read is reported as unreadable rather than as empty, and that the endpoint
carries the caveats along with the numbers.

The recurring theme is the one thing an adapter can quietly get wrong — filling
a gap with a plausible value. Every test here that looks like it is about a
missing price is really about that.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine
from services import portfolio_view as pv


@pytest.fixture()
def paper():
    return PaperExecutionEngine(SqliteLedger(":memory:"), starting_balance=10_000.0)


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    return TestClient(hub_app.app)


def _open(paper, symbol="BTCUSDT", size=1.0, entry=100.0, stop=95.0, side="BUY"):
    return paper.open(symbol=symbol, side=side, size=size, entry=entry,
                      stop=stop, alert_id=f"a-{symbol}-{entry}")


# ── the paper account as a venue ────────────────────────────────────────────

def test_the_paper_account_becomes_one_venue(paper):
    v = pv.paper_venue(paper)
    assert v.venue == pv.PAPER_VENUE
    assert v.cash == 10_000.0
    assert v.positions == ()


def test_equity_matches_the_paper_engines_own_definition(paper):
    """Two definitions of equity for one account is how a portfolio page and an
    account page start disagreeing about the same money."""
    _open(paper, size=2, entry=100)
    marks = {"BTCUSDT": 120.0}
    venue = pv.paper_venue(paper, marks)
    assert venue.equity == pytest.approx(paper.equity(marks))


def test_open_notional_is_carried_as_committed_margin(paper):
    _open(paper, size=3, entry=100)
    v = pv.paper_venue(paper, {"BTCUSDT": 100.0})
    assert v.used_margin == pytest.approx(paper.open_notional())
    assert v.free_margin == pytest.approx(paper.available_balance())


def test_a_position_without_a_price_stays_unmarked(paper):
    """The adapter's single most important refusal. Falling back to entry would
    report an open loss as break-even, and nothing downstream could tell."""
    _open(paper)
    v = pv.paper_venue(paper, marks={})
    assert v.positions[0].mark is None
    assert v.unrealized_pnl is None
    assert v.equity is None


def test_direction_survives_the_translation(paper):
    _open(paper, side="SELL", entry=100, stop=105)
    v = pv.paper_venue(paper)
    assert v.positions[0].direction.value == "short"


# ── brokers the platform cannot read ────────────────────────────────────────

class _Broker:
    def __init__(self, name, connected=True):
        self.name, self._connected = name, connected

    def connected(self):
        return self._connected


class _Registry:
    """Shaped like the real ``BrokerRegistry``: ``brokers`` maps kind → broker."""

    def __init__(self, brokers):
        self.brokers = brokers


def test_the_real_registry_is_read_without_adaptation(monkeypatch):
    """Pinned because the first version of this adapter read a shape the
    registry does not have — ``list()`` returns a status document, not a mapping
    of venues — and every endpoint 500'd."""
    from services.broker import BrokerRegistry
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    venues = pv.broker_venues(BrokerRegistry())
    assert {v.venue for v in venues} == {"binance"}
    assert venues[0].kind.value == "exchange"


def test_an_unconfigured_venue_is_not_part_of_the_portfolio():
    """The registry lists every venue the platform COULD support. Reporting all
    of them as unreachable put four permanent caveats on every snapshot and made
    ``available`` false forever — a warning nobody would read by the second day.
    """
    from services.broker import BrokerRegistry
    for name in ("BINANCE_API_KEY", "BYBIT_API_KEY", "IBKR_API_KEY",
                 "ALPACA_API_KEY"):
        assert name not in __import__("os").environ, (
            f"{name} is set in the test environment — this test cannot measure "
            "what it claims to")
    assert pv.broker_venues(BrokerRegistry()) == ()


def test_exchanges_and_brokers_are_labelled_distinctly():
    venues = pv.broker_venues(_Registry({"binance": _Broker("Binance"),
                                         "ibkr": _Broker("Interactive Brokers")}))
    kinds = {v.venue: v.kind.value for v in venues}
    assert kinds == {"binance": "exchange", "ibkr": "broker"}


def test_a_broker_with_no_balance_api_is_unreachable_not_empty():
    """Reporting it as a zero-balance account would fold a real balance into the
    totals as nothing, and the page would look complete while describing only
    the paper account."""
    v = pv.broker_venues(_Registry({"ibkr": _Broker("Interactive Brokers")}))[0]
    assert v.reachable is False
    assert "no balance endpoint" in v.note
    assert "Interactive Brokers" in v.note


def test_a_disconnected_broker_is_omitted_entirely():
    assert pv.broker_venues(_Registry({"ibkr": _Broker("IB", connected=False)})) == ()


def test_a_broker_that_raises_on_connected_is_not_treated_as_connected():
    """Fail closed on the connectivity probe: a broker that cannot answer
    "are you there?" has not proven it holds anything."""
    class _Broken:
        name = "Flaky"

        def connected(self):
            raise RuntimeError("network down")

    assert pv.broker_venues(_Registry({"bybit": _Broken()})) == ()


def test_the_paper_venue_is_not_duplicated_by_the_registry():
    """The registry holds a paper broker too; counting it twice would double the
    account's balance."""
    venues = pv.broker_venues(_Registry({"paper": _Broker("Paper"),
                                         "binance": _Broker("Binance")}))
    assert [v.venue for v in venues] == ["binance"]


def test_no_registry_is_not_an_error():
    assert pv.broker_venues(None) == ()


# ── the equity curve ────────────────────────────────────────────────────────

def test_the_curve_has_one_point_per_closed_trade(paper):
    _open(paper, size=1, entry=100)
    paper.close(symbol="BTCUSDT", exit_price=110)
    curve = pv.realized_equity_curve(paper)
    assert len(curve) == 2               # opening equity + one close
    assert curve[-1].equity > curve[0].equity


def test_an_account_with_no_closed_trades_has_no_curve(paper):
    """Not a flat line at the starting balance — there are no observations, and
    a fabricated one would produce a 0% return for a period that never ran."""
    _open(paper)
    assert pv.realized_equity_curve(paper) == ()


def test_curve_timestamps_are_timezone_aware(paper):
    """A naive datetime compared against an aware one raises rather than
    sorting, so one naive row would take down the whole curve."""
    _open(paper)
    paper.close(symbol="BTCUSDT", exit_price=110)
    assert all(p.at.tzinfo is not None for p in pv.realized_equity_curve(paper))


def test_the_curve_is_chronological(paper):
    for i, price in enumerate((110, 90, 130)):
        _open(paper, symbol=f"SYM{i}", entry=100)
        paper.close(symbol=f"SYM{i}", exit_price=price)
    curve = pv.realized_equity_curve(paper)
    assert [p.at for p in curve] == sorted(p.at for p in curve)


def test_parse_handles_the_shapes_the_ledger_actually_writes():
    assert pv._parse("2026-07-29T12:00:00Z").tzinfo is not None
    assert pv._parse("2026-07-29T12:00:00").tzinfo is not None
    assert pv._parse(datetime(2026, 7, 29)).tzinfo is not None
    assert pv._parse(None) is None
    assert pv._parse("not a date") is None


# ── the assembled snapshot ──────────────────────────────────────────────────

def test_the_snapshot_reports_every_tracked_figure(paper):
    _open(paper, size=1, entry=100)
    paper.close(symbol="BTCUSDT", exit_price=120)
    data = pv.snapshot(paper=paper, marks={})
    for field in ("balance", "equity", "buying_power", "used_margin",
                  "gross_exposure", "unrealized_pnl", "realized_pnl",
                  "daily_return", "monthly_return", "win_rate", "expectancy",
                  "sharpe_ratio", "max_drawdown_pct"):
        assert field in data, f"{field} is missing from the portfolio snapshot"


def test_the_caveats_travel_with_the_numbers(paper):
    """There must be no version of this payload that carries the figures without
    what qualifies them."""
    _open(paper)
    data = pv.snapshot(paper=paper, marks={})
    assert data["available"] is False
    assert any("no live price" in n for n in data["notes"])


def test_a_realised_only_curve_says_so(paper):
    """Sharpe from trade-to-trade equity is not Sharpe from daily marks, and the
    difference is not visible in the number itself."""
    _open(paper)
    paper.close(symbol="BTCUSDT", exit_price=110)
    data = pv.snapshot(paper=paper, marks={"BTCUSDT": 110.0})
    assert any("realised-only" in b for b in data["basis"])


def test_how_a_figure_is_derived_is_not_filed_as_something_missing(paper):
    """``basis`` is permanent, ``notes`` is fixable, and mixing them made
    ``available`` false on every call — including snapshots with nothing wrong.
    A warning that is always on is one nobody reads."""
    _open(paper)
    paper.close(symbol="BTCUSDT", exit_price=110)
    data = pv.snapshot(paper=paper, marks={})
    assert not any("realised-only" in n for n in data["notes"])
    assert data["basis"]


def test_supplying_the_marks_clears_the_price_note(paper):
    """The gap notes must actually respond to the gap being closed."""
    _open(paper)
    with_marks = pv.snapshot(paper=paper, marks={"BTCUSDT": 105.0})
    assert not any("no live price" in n for n in with_marks["notes"])
    assert with_marks["equity"] is not None


def test_the_snapshot_is_json_safe(paper):
    import json
    _open(paper, size=1, entry=100)
    paper.close(symbol="BTCUSDT", exit_price=90)
    json.dumps(pv.snapshot(paper=paper, marks={}))


def test_unavailable_figures_stay_null_through_serialisation(paper):
    import json
    _open(paper)
    data = json.loads(json.dumps(pv.snapshot(paper=paper, marks={})))
    assert data["equity"] is None
    assert data["unrealized_pnl"] is None


def test_the_paper_account_and_a_live_broker_aggregate_together(paper):
    """The requirement: multiple brokers and exchanges, simultaneously."""
    data = pv.snapshot(paper=paper, registry=_Registry({"binance": _Broker("Binance")}),
                       marks={})
    assert {v["venue"] for v in data["per_venue"]} == {"paper", "binance"}
    # The unreadable venue contributes nothing to the totals but is still listed.
    assert data["balance"] == 10_000.0
    assert any("binance" in n for n in data["notes"])


# ── the endpoints ───────────────────────────────────────────────────────────

def _auth() -> dict:
    import app as hub_app
    return {"X-Webhook-Secret": hub_app.settings.webhook_secret}


def test_the_snapshot_endpoint_answers(client):
    r = client.get("/portfolio/snapshot?marks=false", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert "equity" in body and "per_venue" in body and "notes" in body
    assert "basis" in body


def test_the_venues_endpoint_answers(client):
    r = client.get("/portfolio/venues?marks=false", headers=_auth())
    assert r.status_code == 200
    assert isinstance(r.json()["venues"], list)


def test_the_portfolio_endpoints_are_behind_the_auth_wall(client):
    """Account balances across every venue are the most sensitive read on the
    platform. An unauthenticated 200 here would expose the whole book."""
    for path in ("/portfolio/snapshot", "/portfolio/venues"):
        assert client.get(path).status_code == 401, path


def test_the_endpoint_never_invents_a_mark_when_prices_are_off(client):
    """``marks=false`` is the switch used by tests and by deployments where the
    exchange refuses the request. It must produce "unknown", not "zero"."""
    body = client.get("/portfolio/snapshot?marks=false", headers=_auth()).json()
    if body["per_venue"] and body["per_venue"][0]["position_count"]:
        assert body["equity"] is None
