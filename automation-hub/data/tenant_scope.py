"""Reusable SQLite tenant-scoping primitives — Phase C-1.

``ensure_tenant_column`` is the expand-migrate step for the many stores that are
currently a flat table of rows (ledger ``paper_trades``/``positions``/``bot_logs``
/``alerts``, ``cycle_reports``, ``decisions``, …): it adds a ``tenant_id`` column
defaulting to the owner and backfills existing rows to the owner, so nothing is
observably different until reads start filtering by tenant (a later phase). It is
**idempotent** — safe to call on every boot. See ``docs/PHASE_C_TENANCY.md``.
"""
from __future__ import annotations

import sqlite3

from services.tenancy import OWNER_TENANT


def ensure_tenant_column(conn: sqlite3.Connection, table: str, owner: str = OWNER_TENANT) -> bool:
    """Add ``tenant_id`` to ``table`` (default = owner) if missing; backfill existing
    rows to the owner. Returns True if the column was added, False if already present.
    Idempotent."""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if not cols:
        return False  # table doesn't exist yet — nothing to migrate
    if "tenant_id" in cols:
        return False
    # SQLite requires a constant DEFAULT in ALTER ADD COLUMN; owner is a literal.
    conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '{owner}'")
    # existing rows already got the DEFAULT; make the backfill explicit for clarity
    conn.execute(f"UPDATE {table} SET tenant_id = ? WHERE tenant_id IS NULL OR tenant_id = ''", (owner,))
    conn.commit()
    return True
