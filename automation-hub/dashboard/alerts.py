"""Recent-activity / alerts feed built from bot event streams."""
from __future__ import annotations

from typing import Iterable

_LABELS = {
    "run_started": "Bot started",
    "signal": "Signal generated",
    "order": "Order placed",
    "fill": "Trade opened",
    "trade_closed": "Trade closed",
    "risk_block": "Risk block",
    "run_finished": "Run finished",
}


def recent_activity(bots: Iterable, limit: int = 12) -> list[dict]:
    """Flatten the most recent notable events across all bots."""
    items: list[dict] = []
    for bot in bots:
        for ev in bot.runtime.events:
            t = ev.get("type")
            if t not in _LABELS:
                continue
            detail = _detail(ev)
            items.append({
                "bot": bot.config.name,
                "label": _label_for(ev),
                "detail": detail,
                "ts": ev.get("ts") or ev.get("bar_ts") or "",
            })
    items.sort(key=lambda x: str(x["ts"]), reverse=True)
    return items[:limit]


def _label_for(ev: dict) -> str:
    if ev.get("type") == "trade_closed":
        return "TP hit" if ev.get("pnl", 0) >= 0 else "SL hit"
    return _LABELS.get(ev.get("type"), "Event")


def _detail(ev: dict) -> str:
    t = ev.get("type")
    if t == "signal":
        return f"{ev.get('side','').upper()} {ev.get('symbol','')}"
    if t == "trade_closed":
        return f"PnL {ev.get('pnl',0):.2f} (R {ev.get('r',0):.2f})"
    if t == "risk_block":
        return ev.get("reason", "")
    if t == "fill":
        return f"{ev.get('side','').upper()} {ev.get('symbol','')} @ {ev.get('price',0):.2f}"
    return ev.get("symbol", "")
