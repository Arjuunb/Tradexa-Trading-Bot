"""Runtime-adjustable settings with cross-session persistence.

Only the values that are safe to change on a running bot live here (risk per
trade, exposure limit, max drawdown). They override the env defaults and are
persisted to a small JSON file so they survive a restart. Strategy / symbols /
timeframe require an engine restart and stay env-configured (read-only in the UI).
"""
from __future__ import annotations

import json
from pathlib import Path

EDITABLE = ("risk_per_trade_pct", "exposure_limit_pct", "max_drawdown_pct")


def load_overrides(path: str) -> dict:
    try:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text())
            return {k: float(v) for k, v in data.items() if k in EDITABLE}
    except Exception:  # noqa: BLE001 — corrupt/missing file -> no overrides
        pass
    return {}


def save_overrides(path: str, data: dict) -> None:
    clean = {k: float(data[k]) for k in EDITABLE if k in data}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=2))
