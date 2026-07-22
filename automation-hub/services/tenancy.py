"""Multi-tenant foundation — Phase C-1 (behavior-preserving).

Today the hub is single-owner: every request resolves to the OWNER tenant, so all
data access is unchanged. This module is the **one seam** that per-user isolation
keys on. Stores accept a ``tenant_id`` (defaulting to the owner); ``resolve_tenant``
maps an authenticated user to their tenant.

The switch that makes tenants actually diverge is ``HUB_MULTI_USER`` (off by
default). While it is off, ``resolve_tenant`` always returns ``OWNER_TENANT`` — so
introducing tenant-aware stores changes nothing observable. Flipping it on is a
later phase (real accounts + per-tenant engine + RLS); until then this is inert
and safe. See ``docs/PHASE_C_TENANCY.md`` for the store-by-store rollout.
"""
from __future__ import annotations

import os

# Stable id for the single owner's data — independent of the owner's username, so
# a rename never re-homes their trades. All existing data belongs to this tenant.
OWNER_TENANT = "__owner__"


def multi_user_enabled() -> bool:
    """True only when HUB_MULTI_USER is explicitly enabled. Default: single-owner."""
    return os.environ.get("HUB_MULTI_USER", "").strip().lower() in ("1", "true", "yes", "on")


def resolve_tenant(username: str | None) -> str:
    """The tenant id for a request.

    Single-owner (default): always ``OWNER_TENANT`` — behaviour is unchanged.
    Multi-user (HUB_MULTI_USER on): the authenticated username is the tenant key;
    anonymous/unresolved falls back to the owner (never cross-tenant)."""
    if not multi_user_enabled():
        return OWNER_TENANT
    u = (username or "").strip()
    return u or OWNER_TENANT


def is_owner(tenant_id: str) -> bool:
    return tenant_id == OWNER_TENANT
