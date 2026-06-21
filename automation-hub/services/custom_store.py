"""Persistent store for user-built custom strategies (JSON file)."""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CustomStore:
    def __init__(self, path: str):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001 — corrupt file -> empty
            pass
        return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def list(self) -> list:
        return sorted(self._load().values(), key=lambda s: s.get("updated_at", ""), reverse=True)

    def get(self, sid: str):
        return self._load().get(sid)

    def save(self, spec: dict) -> dict:
        data = self._load()
        sid = spec.get("id") or uuid.uuid4().hex
        spec["id"] = sid
        spec.setdefault("created_at", _now())
        spec["updated_at"] = _now()
        data[sid] = spec
        self._write(data)
        return spec

    def delete(self, sid: str) -> bool:
        data = self._load()
        if sid in data:
            del data[sid]
            self._write(data)
            return True
        return False

    def set_favorite(self, sid: str, fav: bool):
        data = self._load()
        if sid not in data:
            return None
        data[sid]["favorite"] = bool(fav)
        data[sid]["updated_at"] = _now()
        self._write(data)
        return data[sid]

    def set_tags(self, sid: str, tags: list):
        data = self._load()
        if sid not in data:
            return None
        data[sid]["tags"] = [str(t).strip() for t in (tags or []) if str(t).strip()][:8]
        data[sid]["updated_at"] = _now()
        self._write(data)
        return data[sid]

    def duplicate(self, sid: str):
        data = self._load()
        src = data.get(sid)
        if not src:
            return None
        c = copy.deepcopy(src)
        c["id"] = uuid.uuid4().hex
        c["name"] = (src.get("name") or "Strategy") + " (copy)"
        c["created_at"] = c["updated_at"] = _now()
        data[c["id"]] = c
        self._write(data)
        return c
