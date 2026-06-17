"""Local UI-preference store (SQLite). Real persistence for UI-only settings
like theme — trading data lives in the backend, never here."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DB = Path(os.environ.get("BOT_UI_DB", str(Path(__file__).resolve().parent / "ui_prefs.db")))


def _conn() -> sqlite3.connect:
    c = sqlite3.connect(str(_DB))
    c.execute("CREATE TABLE IF NOT EXISTS prefs (k TEXT PRIMARY KEY, v TEXT)")
    return c


def get_pref(key: str, default=None):
    c = _conn()
    try:
        row = c.execute("SELECT v FROM prefs WHERE k=?", (key,)).fetchone()
        return row[0] if row else default
    finally:
        c.close()


def set_pref(key: str, value) -> None:
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO prefs(k, v) VALUES (?, ?)", (key, str(value)))
        c.commit()
    finally:
        c.close()
