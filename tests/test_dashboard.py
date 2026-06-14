"""Dashboard route smoke tests — start server in thread, hit endpoints."""
import json
import socket
import threading
import time
import urllib.request

from bot.dashboard import serve
from bot.events import EventBus


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start(bus):
    port = _free_port()
    srv = serve(bus, host="127.0.0.1", port=port,
                open_browser=False, blocking=False)
    # Wait briefly for the server thread to bind
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                   timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    return srv, port


def test_health_and_state_routes():
    bus = EventBus()
    bus.publish({"type": "run_started", "run_id": "abc",
                 "kind": "backtest", "symbols": ["X"], "starting_cash": 1000,
                 "ts": "2025-01-01"})
    srv, port = _start(bus)
    try:
        h = urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                   timeout=2).read()
        assert h == b"ok"
        st = urllib.request.urlopen(f"http://127.0.0.1:{port}/state",
                                    timeout=2).read()
        body = json.loads(st)
        assert "events" in body
        assert any(e.get("type") == "run_started" for e in body["events"])
    finally:
        srv.shutdown()


def test_index_route_returns_html():
    bus = EventBus()
    srv, port = _start(bus)
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/",
                                   timeout=2)
        body = r.read().decode("utf-8")
        assert "Trading bot dashboard" in body
        assert "EventSource" in body  # SSE client baked in
    finally:
        srv.shutdown()


def test_404_for_unknown_route():
    bus = EventBus()
    srv, port = _start(bus)
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope",
                                   timeout=2)
            assert False, "should have 404'd"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
