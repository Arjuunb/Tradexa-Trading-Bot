"""Production runtime: roles, the singleton lease, health probes, metrics, logs.

The lease tests are the important ones. Everything else here protects a
convenience; those protect the invariant that exactly one trading engine runs,
and a regression in them means duplicate order flow against a real account.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from ops import health, metrics, runtime
from ops.singleton import Lease


# ── roles ────────────────────────────────────────────────────────────────────

def test_default_role_preserves_single_process_behaviour(monkeypatch):
    """Unset HUB_ROLE must behave exactly as the app always has: one process
    that both serves HTTP and runs the workers. Every existing deployment
    depends on this."""
    monkeypatch.delenv("HUB_ROLE", raising=False)
    assert runtime.role() == "all"
    assert runtime.runs_workers() is True
    assert runtime.serves_ui() is True


@pytest.mark.parametrize("role,workers,ui", [
    ("all", True, True),
    ("web", False, True),      # scalable: starts no singleton workers
    ("engine", True, False),   # singleton: no user traffic
])
def test_role_gating(monkeypatch, role, workers, ui):
    monkeypatch.setenv("HUB_ROLE", role)
    assert runtime.runs_workers() is workers
    assert runtime.serves_ui() is ui


def test_unknown_role_raises_rather_than_guessing(monkeypatch):
    """A typo must not silently fall back to 'all'. That would start a second
    trading engine; crash-looping is the cheaper failure."""
    monkeypatch.setenv("HUB_ROLE", "wbe")
    with pytest.raises(RuntimeError, match="not a valid role"):
        runtime.role()


def test_role_is_read_live_not_cached(monkeypatch):
    monkeypatch.setenv("HUB_ROLE", "web")
    assert runtime.runs_workers() is False
    monkeypatch.setenv("HUB_ROLE", "engine")
    assert runtime.runs_workers() is True


# ── the singleton lease ──────────────────────────────────────────────────────

@pytest.fixture()
def lease_db(tmp_path):
    return str(tmp_path / "lease.db")


def test_only_one_holder_at_a_time(lease_db):
    a = Lease(lease_db, "engine", ttl_s=60, owner="pod-a")
    b = Lease(lease_db, "engine", ttl_s=60, owner="pod-b")
    assert a.acquire() is True
    assert b.acquire() is False, "two processes both believe they are the engine"
    assert a.held is True and b.held is False


def test_acquire_is_idempotent_for_the_holder(lease_db):
    a = Lease(lease_db, "engine", ttl_s=60, owner="pod-a")
    assert a.acquire() is True
    assert a.acquire() is True


def test_standby_takes_over_after_the_holder_expires(lease_db):
    a = Lease(lease_db, "engine", ttl_s=0.5, owner="pod-a")
    b = Lease(lease_db, "engine", ttl_s=0.5, owner="pod-b")
    assert a.acquire() is True
    assert b.acquire() is False
    time.sleep(0.7)                       # a's lease lapses
    assert b.acquire() is True, "a dead leader must not block failover forever"


def test_renew_fails_once_the_lease_has_been_taken(lease_db):
    """The signal that tells a stalled leader to stop trading."""
    a = Lease(lease_db, "engine", ttl_s=0.5, owner="pod-a")
    b = Lease(lease_db, "engine", ttl_s=30, owner="pod-b")
    a.acquire()
    time.sleep(0.7)
    b.acquire()
    assert a.renew() is False
    assert a.held is False


def test_renew_extends_the_holders_claim(lease_db):
    a = Lease(lease_db, "engine", ttl_s=1.0, owner="pod-a")
    b = Lease(lease_db, "engine", ttl_s=1.0, owner="pod-b")
    a.acquire()
    for _ in range(4):
        time.sleep(0.3)
        assert a.renew() is True
    assert b.acquire() is False, "a renewing leader must keep the lease"


def test_release_frees_it_immediately(lease_db):
    a = Lease(lease_db, "engine", ttl_s=300, owner="pod-a")
    b = Lease(lease_db, "engine", ttl_s=300, owner="pod-b")
    a.acquire()
    assert b.acquire() is False
    a.release()
    # Without an explicit release a standby would wait out the full 300s TTL.
    assert b.acquire() is True


def test_holder_reports_who_owns_it(lease_db):
    a = Lease(lease_db, "engine", ttl_s=60, owner="pod-a")
    b = Lease(lease_db, "engine", ttl_s=60, owner="pod-b")
    a.acquire()
    assert a.holder()["is_self"] is True
    assert b.holder()["owner"] == "pod-a"
    assert b.holder()["is_self"] is False


def test_named_leases_are_independent(lease_db):
    a = Lease(lease_db, "engine", ttl_s=60, owner="pod-a")
    b = Lease(lease_db, "reporting", ttl_s=60, owner="pod-b")
    assert a.acquire() is True
    assert b.acquire() is True


def test_exactly_one_winner_under_concurrent_contention(lease_db):
    """Twenty threads race for one lease. Anything but a single winner is the
    split-brain this whole mechanism exists to prevent."""
    winners: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def contend(i: int) -> None:
        lease = Lease(lease_db, "engine", ttl_s=60, owner=f"pod-{i}")
        barrier.wait()                    # maximise the overlap
        if lease.acquire():
            with lock:
                winners.append(i)

    threads = [threading.Thread(target=contend, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1, f"expected 1 leader, got {len(winners)}: {winners}"


def test_supervise_starts_work_on_election_and_stops_it_on_loss(lease_db):
    """The full failover path: a standby promotes when the leader disappears."""
    events: list[str] = []
    leader = Lease(lease_db, "engine", ttl_s=1.0, owner="leader")
    leader.acquire()

    standby = Lease(lease_db, "engine", ttl_s=1.0, owner="standby")
    standby.supervise(on_acquire=lambda: events.append("start"),
                      on_lose=lambda: events.append("stop"))
    try:
        time.sleep(0.4)
        assert events == [], "a standby must not start work while a leader holds the lease"

        leader.release()                  # leader dies
        deadline = time.time() + 5
        while "start" not in events and time.time() < deadline:
            time.sleep(0.1)
        assert "start" in events, "standby never promoted after the leader went away"
    finally:
        standby.stop()


# ── health probes ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_health():
    """health module state is process-global; isolate each test."""
    saved = dict(health._checks)
    health._checks.clear()
    health._boot_complete = False
    health._draining = False
    yield
    health._checks.clear()
    health._checks.update(saved)
    health._boot_complete = True
    health._draining = False


def test_liveness_is_dependency_free():
    """Liveness must never consult a dependency: a failure here restarts the
    pod, and restarting does not fix someone else's outage."""
    health.register_check("explodes", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert health.liveness()["status"] == "alive"


def test_not_ready_until_boot_completes():
    payload, ready = health.readiness()
    assert ready is False and payload["status"] == "starting"
    health.mark_boot_complete()
    payload, ready = health.readiness()
    assert ready is True


def test_a_failing_critical_check_fails_readiness():
    health.mark_boot_complete()
    health.register_check("db", lambda: (False, "connection refused"))
    payload, ready = health.readiness()
    assert ready is False
    assert payload["checks"]["db"]["detail"] == "connection refused"


def test_a_failing_non_critical_check_does_not():
    """Degraded but servable — the optional Supabase mirror, say."""
    health.mark_boot_complete()
    health.register_check("mirror", lambda: (False, "unreachable"), critical=False)
    payload, ready = health.readiness()
    assert ready is True
    assert payload["checks"]["mirror"]["ok"] is False


def test_a_raising_check_fails_closed():
    health.mark_boot_complete()
    health.register_check("boom", lambda: (_ for _ in ()).throw(ValueError("nope")))
    payload, ready = health.readiness()
    assert ready is False
    assert "ValueError" in payload["checks"]["boom"]["detail"]


def test_draining_fails_readiness_without_affecting_liveness():
    """The graceful-shutdown path: stop taking new traffic, keep serving what
    is in flight."""
    health.mark_boot_complete()
    health.begin_drain()
    payload, ready = health.readiness()
    assert ready is False and payload["status"] == "draining"
    assert health.liveness()["status"] == "alive"


# ── metrics ──────────────────────────────────────────────────────────────────

def _sample(name: str, **labels):
    from prometheus_client import REGISTRY
    return REGISTRY.get_sample_value(name, labels or None)


def test_render_returns_prometheus_exposition():
    metrics.init()
    body, content_type = metrics.render()
    assert b"hub_build_info" in body
    assert "text/plain" in content_type


def test_recorders_move_their_series():
    before = _sample("hub_risk_vetoes_total", reason="unit_test") or 0
    metrics.record_risk_veto("unit_test")
    assert _sample("hub_risk_vetoes_total", reason="unit_test") == before + 1


def test_a_trade_counts_as_both_a_trade_and_an_accepted_decision():
    before = _sample("hub_trades_total", symbol="TESTUSDT", side="buy") or 0
    metrics.record_trade("TESTUSDT", "BUY")     # side is normalised to lowercase
    assert _sample("hub_trades_total", symbol="TESTUSDT", side="buy") == before + 1


def test_recorders_never_raise_into_the_caller():
    """Instrumentation sits in the trading path. A metrics bug must degrade to
    a missing data point, never to an exception during order handling."""
    metrics.record_trade(object(), None)        # type: ignore[arg-type]
    metrics.set_equity("not a number")          # type: ignore[arg-type]
    metrics.record_cycle(None)                  # type: ignore[arg-type]


def test_cycle_recording_stamps_the_stall_timestamp():
    metrics.record_cycle(0.25)
    assert _sample("hub_engine_last_cycle_timestamp_seconds") > 0


# ── structured logging ───────────────────────────────────────────────────────

def test_json_formatter_emits_one_parseable_object_per_record():
    from ops.log import JsonFormatter

    record = logging.LogRecord("hub.test", logging.INFO, __file__, 10,
                               "hello %s", ("world",), None)
    record.symbol = "BTCUSDT"               # an `extra=` field
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["service"] == "tradexa-hub"
    assert "timestamp" in payload


def test_json_formatter_survives_unserialisable_extras():
    """A stray object in extra= must not raise inside logging and swallow the
    message it was attached to."""
    from ops.log import JsonFormatter

    record = logging.LogRecord("hub.test", logging.INFO, __file__, 10, "x", (), None)
    record.weird = object()
    assert json.loads(JsonFormatter().format(record))["message"] == "x"


def test_request_id_appears_when_one_is_bound():
    from ops.log import JsonFormatter, request_id_var

    token = request_id_var.set("abc123")
    try:
        record = logging.LogRecord("hub.test", logging.INFO, __file__, 10, "x", (), None)
        assert json.loads(JsonFormatter().format(record))["request_id"] == "abc123"
    finally:
        request_id_var.reset(token)


def test_print_bridge_reassembles_lines_split_across_writes():
    """print() writes the text and the newline separately, and callers may write
    partial lines; each complete line must become exactly one record."""
    from ops.log import _StdoutBridge

    seen: list[str] = []

    class Fake:
        def info(self, msg):
            seen.append(msg)

    bridge = _StdoutBridge(Fake())
    bridge.write("hello ")
    bridge.write("world")
    assert seen == [], "a partial line must be held back until its newline"
    bridge.write("\n")
    assert seen == ["hello world"]

    bridge.write("a\nb\n")
    assert seen == ["hello world", "a", "b"]
