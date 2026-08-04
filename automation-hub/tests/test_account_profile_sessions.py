"""Account profile, device sessions, and deletion.

The three things a multi-user SaaS needs that credential storage alone does not
provide: a person's account has a name and a timezone, a person can see and
revoke the devices signed into it, and a person can leave.

The tests that matter most here are the negative ones. A delete that still
authenticates, a revoke that spares the session, and a revocation that reaches
across accounts are each a security hole rather than a missing feature — and
each is the failure the obvious implementation produces.
"""
from __future__ import annotations

import pytest

from database.store import SqliteStore


@pytest.fixture()
def store():
    s = SqliteStore(":memory:")
    s.create_user("alice@example.com", "correct-horse-battery")
    return s


# ═══════════════════════════════════════════ profile

def test_a_new_account_has_a_display_name_without_a_full_name(store):
    """A UI must render something a person recognises on day one, before they
    have filled anything in — not an empty string."""
    assert store.get_user("alice@example.com").display_name


def test_the_full_name_wins_once_it_is_set(store):
    store.update_profile("alice@example.com", full_name="Alice Chen")
    assert store.get_user("alice@example.com").display_name == "Alice Chen"


def test_updating_one_field_does_not_clear_the_others(store):
    """PATCH semantics. Treating omission as deletion would wipe an avatar every
    time someone changed their timezone."""
    store.update_profile("alice@example.com", full_name="Alice Chen",
                         avatar_url="https://cdn.example/a.png")
    store.update_profile("alice@example.com", timezone="Europe/London")
    user = store.get_user("alice@example.com")
    assert user.full_name == "Alice Chen"
    assert user.avatar_url == "https://cdn.example/a.png"
    assert user.timezone == "Europe/London"


def test_preferences_round_trip_as_a_dict(store):
    store.update_profile("alice@example.com",
                         preferences={"theme": "dark", "rows": 50})
    assert store.get_user("alice@example.com").preferences["theme"] == "dark"


def test_corrupt_preferences_do_not_break_a_login(store):
    """Preferences are not worth a failed sign-in. Corrupt JSON degrades to
    empty rather than raising inside authenticate()."""
    with store._lock:
        store._conn.execute("UPDATE users SET preferences='{not json' WHERE username=?",
                            ("alice@example.com",))
        store._conn.commit()
    assert store.authenticate("alice@example.com", "correct-horse-battery")
    assert store.get_user("alice@example.com").preferences == {}


def test_last_login_is_recorded(store):
    assert store.get_user("alice@example.com").last_login is None
    store.touch_login("alice@example.com")
    assert store.get_user("alice@example.com").last_login is not None


# ═══════════════════════════════════════════ sessions

def _session(store, sid, **kw):
    kw.setdefault("ttl_days", 30)
    return store.create_session("alice@example.com", sid, **kw)


def test_a_session_is_listed_for_its_owner(store):
    _session(store, "s1", user_agent="Chrome on macOS")
    listed = store.list_sessions("alice@example.com")
    assert [s["id"] for s in listed] == ["s1"]
    assert listed[0]["user_agent"] == "Chrome on macOS"


def test_a_revoked_session_stops_being_valid(store):
    """The point of recording sessions: a stateless cookie cannot be revoked
    before it expires."""
    _session(store, "s1")
    assert store.session_is_valid("s1")
    store.revoke_session("alice@example.com", "s1")
    assert not store.session_is_valid("s1")


def test_a_revoked_session_leaves_the_active_list(store):
    _session(store, "s1")
    _session(store, "s2")
    store.revoke_session("alice@example.com", "s2")
    assert [s["id"] for s in store.list_sessions("alice@example.com")] == ["s1"]


def test_a_revoked_session_is_still_auditable(store):
    """"Signed out from Berlin at 14:02" is an answer a security-conscious user
    wants; a deleted row cannot give it."""
    _session(store, "s1")
    store.revoke_session("alice@example.com", "s1", by="admin")
    history = store.list_sessions("alice@example.com", include_revoked=True)
    assert history[0]["revoked_at"] and history[0]["revoked_by"] == "admin"


def test_one_user_cannot_revoke_another_users_session(store):
    """The username is in the WHERE clause, not just checked before it — so this
    holds even if a caller forgets to authorise first."""
    store.create_user("mallory@example.com", "pw12345678")
    _session(store, "alice-session")
    assert store.revoke_session("mallory@example.com", "alice-session") is False
    assert store.session_is_valid("alice-session")


def test_sign_out_everywhere_can_keep_the_current_device(store):
    _session(store, "current")
    _session(store, "old-laptop")
    _session(store, "old-phone")
    revoked = store.revoke_all_sessions("alice@example.com", except_id="current")
    assert revoked == 2
    assert store.session_is_valid("current")
    assert not store.session_is_valid("old-laptop")


def test_an_expired_session_is_refused(store):
    _session(store, "s1", ttl_days=1)
    with store._lock:
        store._conn.execute(
            "UPDATE user_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id='s1'")
        store._conn.commit()
    assert not store.session_is_valid("s1")


def test_a_session_issued_before_this_migration_still_works(store):
    """Failing unknown ids closed would sign out every existing user the moment
    this deploys. Revocation still works for everything issued from now on —
    which is what the guard is actually for."""
    assert store.session_is_valid("cookie-from-last-week")


def test_remembered_sessions_are_visible_as_long_lived(store):
    """A user should be able to SEE that a device was kept signed in."""
    _session(store, "s1", remembered=True)
    assert store.list_sessions("alice@example.com")[0]["remembered"] is True


def test_expired_sessions_can_be_purged(store):
    _session(store, "s1")
    with store._lock:
        store._conn.execute(
            "UPDATE user_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        store._conn.commit()
    assert store.purge_expired_sessions() == 1


# ═══════════════════════════════════════════ deletion

def test_a_deleted_account_cannot_sign_in(store):
    """The whole point of the delete. The first implementation of this passed
    every other test in this file and still let a deleted user log in."""
    assert store.authenticate("alice@example.com", "correct-horse-battery")
    store.soft_delete_user("alice@example.com")
    assert store.authenticate("alice@example.com", "correct-horse-battery") is None


def test_deletion_revokes_every_session_immediately(store):
    """An account that is "deleted but still logged in somewhere" is the worst
    of both."""
    _session(store, "s1")
    _session(store, "s2")
    store.soft_delete_user("alice@example.com")
    assert not store.session_is_valid("s1")
    assert not store.session_is_valid("s2")


def test_deletion_is_recoverable_during_the_grace_period(store):
    store.soft_delete_user("alice@example.com")
    assert store.restore_user("alice@example.com")
    assert store.authenticate("alice@example.com", "correct-horse-battery")


def test_restoring_does_not_resurrect_old_sessions(store):
    """Signing in again is the correct amount of friction after an account was
    deleted."""
    _session(store, "s1")
    store.soft_delete_user("alice@example.com")
    store.restore_user("alice@example.com")
    assert not store.session_is_valid("s1")


def test_deleting_twice_is_not_an_error_and_does_not_move_the_clock(store):
    assert store.soft_delete_user("alice@example.com") is True
    first = store.get_user("alice@example.com").deleted_at
    assert store.soft_delete_user("alice@example.com") is False
    assert store.get_user("alice@example.com").deleted_at == first


def test_a_purge_only_takes_accounts_past_the_grace_period(store):
    store.soft_delete_user("alice@example.com")
    assert store.purge_deleted_users(older_than_days=30) == 0
    assert store.get_user("alice@example.com") is not None


def test_a_purge_removes_the_account_and_its_rows(store):
    _session(store, "s1")
    store.soft_delete_user("alice@example.com")
    with store._lock:
        store._conn.execute(
            "UPDATE users SET deleted_at='2000-01-01T00:00:00+00:00' WHERE username=?",
            ("alice@example.com",))
        store._conn.commit()
    assert store.purge_deleted_users(older_than_days=30) == 1
    assert store.get_user("alice@example.com") is None
    assert store.list_sessions("alice@example.com", include_revoked=True) == []


def test_an_active_account_is_never_purged(store):
    assert store.purge_deleted_users(older_than_days=0) == 0
    assert store.get_user("alice@example.com") is not None


# ═══════════════════════════════════════════ migration safety

def test_existing_accounts_survive_the_migration_with_usable_defaults(store):
    """0005 is additive: every new column is nullable or defaulted, so a row
    written before it stays valid and every existing query keeps working."""
    user = store.get_user("alice@example.com")
    assert user.active
    assert user.preferences == {}
    assert user.full_name is None and user.timezone is None
    assert store.authenticate("alice@example.com", "correct-horse-battery")
