"""RBAC role hierarchy + capability helpers (Sprint 11 scaffolding)."""
from services import rbac


def test_role_ordering():
    assert rbac.rank("viewer") < rbac.rank("operator") < rbac.rank("admin") < rbac.rank("owner")
    assert rbac.rank("nonsense") == -1
    assert rbac.rank("") == -1 and rbac.rank(None) == -1


def test_role_at_least_is_inclusive_and_default_deny():
    assert rbac.role_at_least("owner", "admin")
    assert rbac.role_at_least("admin", "admin")        # inclusive
    assert not rbac.role_at_least("operator", "admin")
    assert not rbac.role_at_least("viewer", "operator")
    # unknown role satisfies nothing; unknown requirement is never satisfied
    assert not rbac.role_at_least("wizard", "viewer")
    assert not rbac.role_at_least("owner", "wizard")


def test_case_and_whitespace_insensitive():
    assert rbac.role_at_least("  Owner ", "operator")
    assert rbac.is_valid_role("ADMIN") and not rbac.is_valid_role("root")


def test_capabilities():
    assert rbac.can("viewer", "view")
    assert not rbac.can("viewer", "trade")
    assert rbac.can("operator", "trade") and rbac.can("operator", "configure")
    assert not rbac.can("operator", "manage_users")
    assert rbac.can("admin", "manage_users")
    assert not rbac.can("admin", "owner_only")
    assert rbac.can("owner", "owner_only")
    # unknown capability is denied for everyone
    assert not rbac.can("owner", "launch_missiles")
