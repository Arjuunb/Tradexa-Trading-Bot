"""Decision Log service (Phase 2 · decision transparency)."""
import datetime as dt

from bot.events import EventBus, ev_bar, ev_order, ev_risk_block, ev_signal

from services.decision_log import DecisionLog

TS = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)


def _sig(sym="BTC/USDT", side="buy", reason="EMA crossed up"):
    return ev_signal(sym, side, 100.0, 95.0, 110.0, reason, TS)


def test_signal_then_order_is_executed():
    log = DecisionLog(strategy="EMA Trend")
    bus = EventBus(); log.attach(bus)
    bus.publish(_sig())
    bus.publish(ev_order("o1", "BTC/USDT", "buy", 1.0))
    bus.publish(ev_bar("BTC/USDT", TS, 100.0, 10000.0))
    recs = log.records()
    assert len(recs) == 1
    assert recs[0].verdict == "executed" and recs[0].strategy == "EMA Trend"
    assert "risk_per_trade" in recs[0].passed


def test_signal_then_risk_block_is_rejected():
    log = DecisionLog()
    bus = EventBus(); log.attach(bus)
    bus.publish(_sig())
    bus.publish(ev_risk_block("BTC/USDT", "Daily loss limit hit (-3.10%)", TS))
    bus.publish(ev_bar("BTC/USDT", TS, 100.0, 10000.0))
    r = log.records()[0]
    assert r.verdict == "rejected" and "Daily loss" in r.reason
    assert r.failed and "Daily loss" in r.failed[0]


def test_signal_not_actioned_is_skipped():
    log = DecisionLog()
    bus = EventBus(); log.attach(bus)
    bus.publish(_sig())                       # signal but no order / no block
    bus.publish(ev_bar("BTC/USDT", TS, 100.0, 10000.0))
    r = log.records()[0]
    assert r.verdict == "skipped"


def test_safety_decision_enriches_with_rules():
    log = DecisionLog()
    bus = EventBus(); log.attach(bus)
    bus.publish(_sig())
    bus.publish(ev_order("o1", "BTC/USDT", "buy", 1.0))    # provisional executed
    bus.publish({                                           # safety gate overwrites
        "type": "decision", "symbol": "BTC/USDT", "side": "buy", "qty": 1.0,
        "verdict": "rejected", "reason": "20.0 bps > 8 bps cap",
        "checks": [
            {"rule": "valid_order", "passed": True, "detail": ""},
            {"rule": "slippage_within_limit", "passed": False, "detail": ""},
        ],
    })
    bus.publish(ev_bar("BTC/USDT", TS, 100.0, 10000.0))
    recs = log.records()
    assert len(recs) == 1                                   # enriched, not duplicated
    assert recs[0].verdict == "rejected"
    assert "valid_order" in recs[0].passed
    assert "slippage_within_limit" in recs[0].failed


def test_recent_and_for_symbol_query():
    log = DecisionLog()
    bus = EventBus(); log.attach(bus)
    for sym in ("BTC/USDT", "ETH/USDT"):
        bus.publish(_sig(sym))
        bus.publish(ev_order("o", sym, "buy", 1.0))
        bus.publish(ev_bar(sym, TS, 1.0, 1.0))
    assert len(log.recent()) == 2
    assert log.recent()[0]["symbol"] == "ETH/USDT"         # most recent first
    assert len(log.for_symbol("BTC/USDT")) == 1


def test_live_runner_populates_decisions():
    from bot.data.synthetic import generate_bars
    from bots.manager import BotManager
    from data.websocket import ReplayFeed
    from database.models import BotConfig, BotMode
    m = BotManager()
    bot = m.create(BotConfig(name="EMA", strategy="ema", exchange="binance",
                             symbol="BTCUSDT", timeframe="1h", mode=BotMode.LIVE))
    m.start_live(bot.id, feed=ReplayFeed(generate_bars(400, "1h", seed=4)))
    m.runner(bot.id).wait(timeout=15)
    decisions = bot.runtime.decisions
    assert decisions, "expected decision records"
    assert {d["verdict"] for d in decisions} <= {"executed", "rejected", "blocked", "skipped"}
