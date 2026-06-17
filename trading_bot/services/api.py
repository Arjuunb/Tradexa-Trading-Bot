"""API layer — a thin client over the existing Automation Hub backend.

Every page reads/writes through this client, so all data is REAL (it comes from
the backend's paper engine, risk pipeline, ledger and backtester). This is also
the seam Tradexa connects to later: swap the base URL or wrap these methods.
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from trading_bot.config import settings


class HubAPI:
    def __init__(self, base_url: Optional[str] = None, secret: Optional[str] = None,
                 session: Optional[requests.Session] = None):
        self.base = (base_url or settings.api_base).rstrip("/")
        self.secret = secret or settings.webhook_secret
        self.s = session or requests.Session()

    # ---- low-level ----
    def _get(self, path: str, **params) -> Any:
        try:
            r = self.s.get(self.base + path, params=params or None, timeout=settings.request_timeout)
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001 — backend down -> None, page shows offline state
            return None

    def _post(self, path: str, body: Any = None) -> dict:
        try:
            r = self.s.post(self.base + path, json=body,
                            headers={"X-Webhook-Secret": self.secret}, timeout=settings.request_timeout + 10)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def _delete(self, path: str) -> dict:
        try:
            r = self.s.delete(self.base + path, headers={"X-Webhook-Secret": self.secret},
                              timeout=settings.request_timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # ---- reads ----
    def system_status(self): return self._get("/system/status")
    def engine_status(self): return self._get("/engine/status")
    def account(self): return self._get("/paper/account")
    def positions(self): return self._get("/paper/positions") or []
    def trades(self): return self._get("/paper/trades") or []
    def equity_curve(self): return self._get("/paper/equity-curve")
    def risk(self): return self._get("/risk/summary")
    def performance(self): return self._get("/strategy/performance")
    def logs(self, limit: int = 200): return self._get("/ledger/logs", limit=limit) or []
    def alerts(self, limit: int = 100): return self._get("/ledger/alerts", limit=limit) or []
    def controls_state(self): return self._get("/controls/state")
    def strategy_list(self): return self._get("/strategy/list")
    def bots_live(self): return self._get("/bots/live") or []
    def settings(self): return self._get("/settings")
    def notif_status(self): return self._get("/notifications/status")
    def custom_list(self): return self._get("/strategy/custom") or []
    def compare(self, symbol, timeframe, strategy, bars=3000):
        return self._get("/strategy/compare", symbol=symbol, timeframe=timeframe, strategy=strategy, bars=bars)

    # ---- actions ----
    def pause(self): return self._post("/controls/pause-all")
    def stop(self): return self._post("/controls/stop-all")
    def resume(self): return self._post("/controls/resume")
    def engine_start(self): return self._post("/engine/start")
    def engine_stop(self): return self._post("/engine/stop")
    def simulate(self, spec: dict, bars: int = 3000): return self._post("/strategy/custom/simulate", {"spec": spec, "bars": bars})
    def save_strategy(self, spec: dict): return self._post("/strategy/custom", spec)
    def delete_strategy(self, sid: str): return self._delete(f"/strategy/custom/{sid}")
    def duplicate_strategy(self, sid: str): return self._post(f"/strategy/custom/{sid}/duplicate", {})
    def deploy_strategy(self, sid: str): return self._post(f"/strategy/custom/{sid}/deploy", {})
    def update_settings(self, body: dict): return self._post("/settings", body)
    def set_symbols(self, symbols: list): return self._post("/market/symbols", {"symbols": symbols})
    def notif_update(self, body: dict): return self._post("/notifications", body)
    def notif_test(self): return self._post("/notifications/test")

    # ---- export URLs (for download buttons) ----
    def export_url(self, kind: str = "logs", fmt: str = "csv") -> str:
        path = {"logs": "/ledger/logs/export", "alerts": "/ledger/alerts/export",
                "trades": "/paper/trades/export"}.get(kind, "/ledger/logs/export")
        return f"{self.base}{path}?fmt={fmt}"
