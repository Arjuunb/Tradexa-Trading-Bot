"""Role-based access control helpers (DSP Sprint 11 scaffolding).

Pure, dependency-free role hierarchy + capability checks for the user roles the
identity layer already carries (users.role: owner | admin | operator | viewer).
These are the building blocks for gating endpoints; wiring them onto routes is a
follow-up. Kept side-effect-free so they are trivially unit-testable.
"""
from __future__ import annotations

# Ascending privilege — index == rank. viewer < operator < admin < owner.
ROLES: tuple[str, ...] = ("viewer", "operator", "admin", "owner")
_RANK = {r: i for i, r in enumerate(ROLES)}

# Minimum role required for a capability. Kept small and explicit; extend as
# endpoints adopt gating.
CAPABILITIES: dict[str, str] = {
    "view": "viewer",          # read dashboards / status / history
    "trade": "operator",       # start/stop engine, open/close paper orders, move SL/TP
    "configure": "operator",   # edit strategy / risk / settings
    "manage_users": "admin",   # create/disable users, change roles
    "owner_only": "owner",     # destructive account-level actions
}


def _norm(role: str | None) -> str:
    return (role or "").strip().lower()


def is_valid_role(role: str | None) -> bool:
    return _norm(role) in _RANK


def rank(role: str | None) -> int:
    """Privilege rank, or -1 for an unknown/empty role (ranks below everything)."""
    return _RANK.get(_norm(role), -1)


def role_at_least(role: str | None, minimum: str) -> bool:
    """True if ``role`` is at least as privileged as ``minimum``. An unknown
    role never satisfies any requirement (default-deny)."""
    r, m = rank(role), rank(minimum)
    return r >= 0 and m >= 0 and r >= m


def can(role: str | None, capability: str) -> bool:
    """True if ``role`` is permitted the given capability (unknown capability →
    denied)."""
    need = CAPABILITIES.get(capability)
    return need is not None and role_at_least(role, need)
