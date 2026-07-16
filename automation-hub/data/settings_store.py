"""Durable per-user settings mirror (Supabase/Postgres).

The SQLite `user_settings` table lives under HUB_DATA_DIR, which is ephemeral on
a free host without a mounted disk — so a restart wiped it and every login showed
defaults. This mirrors the same rows into Supabase (the ledger already uses it),
so settings survive redeploys FOR FREE: SQLite stays the fast local cache, this
is the durable source of truth.

Only used when SUPABASE_URL + SUPABASE_KEY are set. Every method is fail-closed —
a network hiccup returns None / no-ops, so the local cache keeps working and the
app never breaks over settings persistence.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseSettingsStore:
    """PostgREST-backed store for the `user_settings` table (username, namespace,
    data, updated_at) with a (username, namespace) primary key."""

    def __init__(self, url: str, key: str):  # pragma: no cover - needs network + creds
        from supabase import create_client
        self._db = create_client(url, key)

    def get(self, username: str, namespace: str) -> Optional[dict]:  # pragma: no cover
        try:
            res = (self._db.table("user_settings").select("data")
                   .eq("username", username).eq("namespace", namespace).limit(1).execute())
            if res.data:
                return json.loads(res.data[0]["data"]) or {}
        except Exception:  # noqa: BLE001 — unreachable -> fall back to local cache
            return None
        return None

    def set(self, username: str, namespace: str, data: dict) -> None:  # pragma: no cover
        try:
            self._db.table("user_settings").upsert({
                "username": username, "namespace": namespace,
                "data": json.dumps(data), "updated_at": _now(),
            }, on_conflict="username,namespace").execute()
        except Exception:  # noqa: BLE001 — durable write best-effort; local cache still has it
            pass

    def delete(self, username: str, namespace: Optional[str] = None) -> None:  # pragma: no cover
        try:
            q = self._db.table("user_settings").delete().eq("username", username)
            if namespace:
                q = q.eq("namespace", namespace)
            q.execute()
        except Exception:  # noqa: BLE001
            pass


def make_settings_mirror() -> Optional[SupabaseSettingsStore]:
    """Build the mirror from env (SUPABASE_URL + SUPABASE_KEY), else None."""
    import os
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not (url and key):
        return None
    try:
        return SupabaseSettingsStore(url, key)
    except Exception:  # noqa: BLE001 — supabase-py missing / bad creds -> no mirror
        return None
