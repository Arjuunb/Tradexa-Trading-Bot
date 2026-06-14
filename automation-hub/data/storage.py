"""Lightweight JSON persistence for bot configs (stdlib only).

Phase 1 default is in-memory; this lets the BotManager optionally survive a
restart without a database. The ``database/`` package replaces this with a real
ORM + migrations later.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STORE = Path(__file__).resolve().parent.parent / "logs" / "bots.json"


def save(records: list[dict], path: Path = _STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")


def load(path: Path = _STORE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
