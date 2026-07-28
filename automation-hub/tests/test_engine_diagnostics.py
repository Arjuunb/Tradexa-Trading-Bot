"""Engine inactivity diagnosis — the 'why isn't the bot trading?' logic."""
import pytest

from services.auto_engine import explain_inactivity


@pytest.fixture()
def client():
    """Mounts the real router, so the endpoint wiring is exercised rather than
    the pure function a second time."""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI()
    app.include_router(webhook_api.router)
    return TestClient(app)


def _kw(**over):
    base = dict(running=True, trading_state="Active", mode="live", timeframe="4h",
                bars=500, signals=3, trades=2, rejections=1,
                data_source="live (ccxt)", last_activity_age_s=100.0)
    base.update(over)
    return base


def test_stopped():
    assert explain_inactivity(**_kw(running=False))["status"] == "stopped"


def test_halted():
    assert explain_inactivity(**_kw(trading_state="Paused"))["status"] == "halted"


def test_connected_live_feed_with_zero_bars_is_waiting_not_no_data():
    # a HEALTHY live feed with bars=0 means "waiting for the first candle close"
    v = explain_inactivity(**_kw(bars=0))
    assert v["status"] == "waiting_first_candle" and v["severity"] == "info"
    assert "CLOSES" in v["detail"] or "closes" in v["detail"].lower()
    assert "5m" in v["detail"]                 # points to the quick-testing mode


def test_no_data_in_replay_warmup():
    v = explain_inactivity(**_kw(bars=0, mode="replay", data_source=None))
    assert v["status"] == "no_data"


def test_stale_live_feed_is_critical():
    v = explain_inactivity(**_kw(mode="live", data_source="bundled sample"))
    assert v["status"] == "stale_feed" and v["severity"] == "critical"
    assert "Binance" in v["detail"] or "cloud" in v["detail"]


def test_stale_feed_wins_over_generic_no_data():
    # THE bug from production: live mode fell back to synthetic and bars stayed
    # 0 forever — the generic warm-up message must NOT hide the real diagnosis.
    v = explain_inactivity(**_kw(bars=0, mode="live", data_source="synthetic",
                                 feed_error="ExchangeNotAvailable: HTTP 451"))
    assert v["status"] == "stale_feed" and v["severity"] == "critical"
    assert "451" in v["detail"]                # the REAL fetch error is shown
    assert "HUB_EXCHANGE" in v["detail"]       # and the concrete fix


def test_waiting_candles_on_high_timeframe():
    # last candle ~ a day ago on 4h -> infrequent by design
    v = explain_inactivity(**_kw(mode="live", data_source="live (ccxt)",
                                 last_activity_age_s=86400.0))
    assert v["status"] == "waiting_candles"


def test_no_setup_when_no_signals():
    v = explain_inactivity(**_kw(mode="replay", data_source="synthetic",
                                 signals=0, trades=0, rejections=0, last_activity_age_s=5.0))
    assert v["status"] == "no_setup"


def test_all_blocked():
    v = explain_inactivity(**_kw(mode="replay", data_source="synthetic",
                                 signals=5, trades=0, rejections=5, last_activity_age_s=5.0))
    assert v["status"] == "all_blocked" and v["severity"] == "warning"


def test_active():
    v = explain_inactivity(**_kw(mode="replay", data_source="synthetic", last_activity_age_s=5.0))
    assert v["status"] == "active"


def test_endpoint():
    import pytest
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    body = TestClient(app).get("/engine/diagnostics").json()
    assert "status" in body and "headline" in body and "detail" in body


# ─────────────── data feed: per-fetch logging + honest fallbacks ───────────────
def test_fetch_failure_is_recorded_not_silent(monkeypatch):
    """fetch_ohlcv used to swallow every error invisibly — now each attempt is
    recorded (symbol/timeframe/exchange/ok/bars/error) for diagnostics."""
    from data import live_data
    monkeypatch.setitem(live_data.LAST_FETCH, "BTCUSDT", None)  # snapshot-restore
    out = live_data.fetch_ohlcv("BTCUSDT", timeframe="4h",
                                exchange="no_such_exchange_xyz")
    assert out is None
    rec = live_data.LAST_FETCH["BTCUSDT"]
    assert rec["ok"] is False and rec["error"]
    assert rec["timeframe"] == "4h" and rec["exchange"] == "no_such_exchange_xyz"
    assert live_data.last_error("BTCUSDT") == rec["error"]


def test_get_bars_all_symbols_and_timeframes_honest_sources():
    """BTC/ETH/SOL on 5m/15m/4h must always return bars > 0 with an honest
    source label (bundled sample or synthetic here — live is off in tests)."""
    from data.market_data import get_bars
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for tf in ("5m", "15m", "4h"):
            bars, src = get_bars(sym, n=300, timeframe=tf)
            assert len(bars) > 0, f"{sym} {tf}: no bars"
            assert src in ("bundled sample", "synthetic", "local store (real)"), \
                f"{sym} {tf}: unexpected source {src!r}"


def test_engine_status_reports_feed_state():
    """status() must expose feed_status/feed_error so 'Running' can never hide
    a dead feed again."""
    from data.ledger import SqliteLedger
    from execution.paper_engine import PaperExecutionEngine
    from services.auto_engine import AutoStrategyEngine
    from services.controls import TradingControl
    from services.signal_pipeline import SignalPipeline

    led = SqliteLedger(":memory:")
    paper = PaperExecutionEngine(led)
    pipe = SignalPipeline(led, paper, TradingControl(), equity=10_000,
                          risk_per_trade_pct=0.01, exposure_limit_pct=0.5,
                          max_total_exposure_pct=1.0, adaptive_risk=False,
                          equity_throttle=False)
    eng = AutoStrategyEngine(pipe, paper, led, symbols=["BTCUSDT"], live=True)
    eng.last_source = "synthetic"              # live wanted, static delivered
    st = eng.status()
    assert st["feed_status"] == "fallback"
    eng.last_source = "live (ccxt)"
    assert eng.status()["feed_status"] == "waiting-for-candle"   # bars still 0
    eng.stats["bars"] = 3
    assert eng.status()["feed_status"] == "connected"


# ═══════════════════════════════ a zero bar count must explain itself
# "Bars 0" on a 4h timeframe looks identical whether the engine started two
# minutes ago or the feed died overnight. /system/status now carries the same
# verdict /engine/diagnostics does, so the status bar can say which.

def _status_payload(client):
    return client.get("/system/status").json()


def test_system_status_carries_a_bars_verdict(client):
    j = _status_payload(client)
    assert "bars_status" in j and "bars_note" in j and "bars_severity" in j


def test_a_healthy_wait_and_a_dead_feed_do_not_read_the_same():
    """The whole point of the annotation — these two must differ."""
    from services.auto_engine import explain_inactivity
    common = dict(running=True, trading_state="active", timeframe="4h", bars=0,
                  signals=0, trades=0, rejections=0, last_activity_age_s=None)
    waiting = explain_inactivity(mode="live", data_source="live (ccxt)", **common)
    stalled = explain_inactivity(mode="live", data_source="synthetic", **common)

    assert waiting["status"] == "waiting_first_candle"
    assert stalled["status"] == "stale_feed"
    assert waiting["headline"] != stalled["headline"]
    assert waiting["severity"] == "info" and stalled["severity"] == "critical"


def test_the_waiting_verdict_names_the_timeframe_it_is_waiting_on():
    from services.auto_engine import explain_inactivity
    v = explain_inactivity(running=True, trading_state="active", mode="live",
                           timeframe="4h", bars=0, signals=0, trades=0,
                           rejections=0, data_source="live (ccxt)",
                           last_activity_age_s=None)
    assert "4h" in v["detail"] and "hours" in v["detail"]


def test_the_status_bar_and_the_diagnostics_page_agree(client):
    """Two endpoints deriving the same verdict from separately assembled
    arguments is how a status bar ends up contradicting the page it links to."""
    st = _status_payload(client)
    dg = client.get("/engine/diagnostics").json()
    assert st["bars_status"] == dg["status"]
    assert st["bars_note"] == dg["headline"]
    assert st["bars_severity"] == dg["severity"]
