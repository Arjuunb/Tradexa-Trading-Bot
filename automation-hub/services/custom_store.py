"""Persistent store for user-built custom strategies (JSON file)."""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Fields that are library metadata, not part of the strategy DEFINITION. Version
# snapshots capture only the definition, so favourites/tags/folder/history don't
# pollute the diff or nest recursively.
_META_KEYS = {"id", "created_at", "updated_at", "versions", "favorite", "tags", "folder"}
_VERSION_CAP = 30


def _definition(spec: dict) -> dict:
    return {k: v for k, v in spec.items() if k not in _META_KEYS}


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
        existing = data.get(sid)
        versions = list(existing.get("versions", [])) if existing else []
        if existing is not None:
            # snapshot the PREVIOUS state as a version whenever the definition
            # actually changed (renames/param edits/rule edits) — the audit trail.
            if _definition(existing) != _definition(spec):
                versions.append({
                    "v": (versions[-1]["v"] + 1) if versions else 1,
                    "at": existing.get("updated_at") or _now(),
                    "name": existing.get("name"),
                    "spec": _definition(existing),
                })
                versions = versions[-_VERSION_CAP:]
            # library metadata lives on the record, not in each save payload
            for k in ("favorite", "tags", "folder"):
                if k in existing and k not in spec:
                    spec[k] = existing[k]
        spec.setdefault("created_at", existing.get("created_at") if existing else _now())
        spec["updated_at"] = _now()
        spec["versions"] = versions
        data[sid] = spec
        self._write(data)
        return spec

    def history(self, sid: str):
        """Return the version snapshots for a strategy (newest last), or None."""
        s = self._load().get(sid)
        if s is None:
            return None
        return list(s.get("versions", []))

    def restore(self, sid: str, v: int):
        """Roll a strategy back to version `v`. The current state is snapshotted
        first (via save), so a restore is itself undoable."""
        s = self._load().get(sid)
        if not s:
            return None
        ver = next((x for x in s.get("versions", []) if int(x.get("v", -1)) == int(v)), None)
        if ver is None:
            return None
        restored = {**copy.deepcopy(ver["spec"]), "id": sid}
        return self.save(restored)

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

    def set_meta(self, sid: str, *, name=None, folder=None):
        """Rename and/or move a strategy into a folder (library organisation)."""
        data = self._load()
        if sid not in data:
            return None
        if name is not None and str(name).strip():
            data[sid]["name"] = str(name).strip()[:80]
        if folder is not None:
            data[sid]["folder"] = str(folder).strip()[:60]
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
