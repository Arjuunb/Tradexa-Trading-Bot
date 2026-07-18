"""Durable persistence for the server-side grid (paper).

Saves the running grid's snapshot to a local JSON file under HUB_DATA_DIR and,
when Supabase is configured, mirrors it there too — so a running grid survives a
restart / redeploy (the same free-tier durability the settings use). Fail-closed:
persistence never breaks the grid.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_USER = "__hub__"
_NS = "grid-state"
_mirror_cache: dict = {"built": False, "store": None}


def _mirror():
    if not _mirror_cache["built"]:
        _mirror_cache["built"] = True
        try:
            from data.settings_store import make_settings_mirror
            _mirror_cache["store"] = make_settings_mirror()
        except Exception:  # noqa: BLE001
            _mirror_cache["store"] = None
    return _mirror_cache["store"]


def _path() -> Path:
    return Path(os.environ.get("HUB_DATA_DIR", ".")) / "grid.json"


def save(snapshot: Optional[dict]) -> None:
    """Persist the grid snapshot; pass None to clear it (grid stopped)."""
    p = _path()
    try:
        if snapshot is None:
            if p.exists():
                p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(snapshot))
    except Exception:  # noqa: BLE001 — local write best-effort
        pass
    m = _mirror()
    if m is not None:
        try:
            if snapshot is None:
                m.delete(_USER, _NS)
            else:
                m.set(_USER, _NS, snapshot)
        except Exception:  # noqa: BLE001 — durable write best-effort
            pass


def load() -> Optional[dict]:
    try:
        p = _path()
        if p.exists():
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        pass
    m = _mirror()
    if m is not None:
        try:
            return m.get(_USER, _NS)
        except Exception:  # noqa: BLE001
            pass
    return None
