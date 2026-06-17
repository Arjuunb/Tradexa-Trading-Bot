"""HubAPI client: correct paths, secret header on writes, graceful failures."""
from __future__ import annotations

import json

from trading_bot.services.api import HubAPI


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload=None, fail=False):
        self.payload = payload if payload is not None else {"ok": True}
        self.fail = fail
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params, None))
        if self.fail:
            raise ConnectionError("down")
        return FakeResp(self.payload)

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        if self.fail:
            raise ConnectionError("down")
        return FakeResp(self.payload)

    def delete(self, url, headers=None, timeout=None):
        self.calls.append(("DELETE", url, None, headers))
        if self.fail:
            raise ConnectionError("down")
        return FakeResp(self.payload)


def _api(**kw):
    sess = FakeSession(**kw)
    return HubAPI(base_url="http://x", secret="sek", session=sess), sess


def test_get_path_and_parse():
    api, sess = _api(payload={"engine_running": True})
    assert api.system_status() == {"engine_running": True}
    assert sess.calls[0][:2] == ("GET", "http://x/system/status")


def test_get_returns_none_on_failure():
    api, _ = _api(fail=True)
    assert api.system_status() is None
    # list-returning reads default to []
    assert api.trades() == []


def test_post_sends_secret_header():
    api, sess = _api(payload={"ok": True})
    api.pause()
    method, url, body, headers = sess.calls[0]
    assert method == "POST"
    assert url == "http://x/controls/pause-all"
    assert headers["X-Webhook-Secret"] == "sek"


def test_post_returns_error_dict_on_failure():
    api, _ = _api(fail=True)
    res = api.engine_start()
    assert "error" in res


def test_delete_path_and_header():
    api, sess = _api(payload={"deleted": True})
    api.delete_strategy("abc")
    method, url, _, headers = sess.calls[0]
    assert method == "DELETE"
    assert url == "http://x/strategy/custom/abc"
    assert headers["X-Webhook-Secret"] == "sek"


def test_simulate_body_shape():
    api, sess = _api(payload={"metrics": {}})
    api.simulate({"name": "s"}, bars=1000)
    _, url, body, _ = sess.calls[0]
    assert url == "http://x/strategy/custom/simulate"
    assert body == {"spec": {"name": "s"}, "bars": 1000}
    json.dumps(body)  # serialisable


def test_export_url():
    api, _ = _api()
    assert api.export_url("trades", "csv") == "http://x/paper/trades/export?fmt=csv"
