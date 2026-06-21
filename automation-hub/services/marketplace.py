"""Strategy Marketplace (#1).

One catalog over two shelves:
  * Built-in templates  — the strategy registry (clone a rule-based one into your
                          library to tag / favorite / version it).
  * My Library          — your saved custom strategies, with favorite, tags and
                          version history.

Pure aside from the store I/O, so it is unit-testable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from services.strategy_presets import REGISTRY, PRESETS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _describe(spec: dict) -> str:
    rules = ((spec.get("entry") or {}).get("rules")) or spec.get("rules") or []
    kinds = ", ".join(sorted({r.get("type", "rule") for r in rules})) or "custom rules"
    return f"{spec.get('side', 'long')} · {kinds}"


def catalog(store) -> dict:
    """Merged catalog: My Library (custom) + Built-in templates."""
    library = []
    for s in store.list():
        library.append({
            "id": s["id"], "name": s.get("name", "Strategy"), "kind": "custom",
            "source": "My Library", "favorite": bool(s.get("favorite")),
            "tags": s.get("tags", []), "version": s.get("version", "1.0"),
            "symbol": s.get("symbol"), "timeframe": s.get("timeframe"),
            "description": s.get("description") or _describe(s),
            "updated_at": s.get("updated_at", ""),
        })
    library.sort(key=lambda c: c["updated_at"], reverse=True)
    library.sort(key=lambda c: not c["favorite"])           # favorites first (stable)

    templates = [{
        "id": r["id"], "name": r["name"], "kind": "template", "source": "Built-in",
        "favorite": False, "tags": [r["kind"]], "version": r["version"],
        "timeframes": r["timeframes"], "description": r["description"],
        "clonable": PRESETS.get(r["name"], {}).get("kind") == "custom",
    } for r in REGISTRY if r["id"] != "custom"]

    return {
        "library": library, "templates": templates,
        "favorites": [c for c in library if c["favorite"]],
        "tags": sorted({t for c in library for t in c["tags"]}),
        "counts": {"library": len(library), "favorites": sum(1 for c in library if c["favorite"])},
    }


def clone_template(store, template_name: str) -> dict:
    """Clone a rule-based built-in template into the user's library as a new
    editable custom strategy."""
    preset = PRESETS.get(template_name)
    if not preset:
        return {"error": f"unknown template {template_name}"}
    if preset.get("kind") != "custom":
        return {"error": f"'{template_name}' is a built-in engine strategy — activate it on the "
                         "Strategies page; only rule-based templates can be cloned to the library."}
    spec = {
        "id": uuid.uuid4().hex, "name": f"{template_name} (template)",
        "symbol": "BTCUSDT", "timeframe": preset.get("timeframe", "4h"),
        "side": preset.get("side", "long"),
        "entry": {"op": "AND", "rules": [dict(r) for r in preset["rules"]]},
        "stop": {"type": "atr", "mult": 1.5, "period": 14},
        "target": {"type": "rr", "rr": 2.0}, "risk_per_trade_pct": 0.01,
        "min_score": 60, "tags": ["template"], "favorite": False,
        "description": f"Cloned from the built-in {template_name} template.",
    }
    return store.save(spec)
