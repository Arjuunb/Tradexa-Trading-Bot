"""The admin portal's authorisation policy, and its session tokens.

Every test here is a way a user-management surface gets someone owned. They are
worth more than the portal's HTML: a page that renders wrongly is a bug report,
a policy that answers wrongly is a privilege escalation.

Two properties are being defended.

**Separation.** The portal runs as its own process precisely so that a
compromised trading app is not a compromised admin surface. That is only true if
a trading-app cookie cannot be presented here — which is a property of the
signing key, not of the deployment topology, so it is tested directly.

**No upward reach.** Nobody grants, takes, or overrides privilege at or above
their own level, and the deployment can never be left with no administrator.
"""
from __future__ import annotations

import time

import pytest

from database.models import User
from services import admin_portal as ap
from services.session_auth import sign, sign_scoped


SECRET = "portal-test-secret"


def _u(username, role="operator", deleted=False):
    from datetime import datetime, timezone
    return User(username=username, role=role,
                deleted_at=datetime.now(timezone.utc) if deleted else None)


OWNER = _u("owner@example.com", "owner")
ADMIN = _u("admin@example.com", "admin")
ADMIN2 = _u("admin2@example.com", "admin")
OPERATOR = _u("op@example.com", "operator")
VIEWER = _u("viewer@example.com", "viewer")
EVERYONE = [OWNER, ADMIN, ADMIN2, OPERATOR, VIEWER]


# ═══════════════════════════════════════════ token separation

def test_a_trading_app_cookie_is_not_a_portal_cookie():
    """The whole point of running the portal as a separate app. If this fails,
    stealing any signed-in user's cookie is an admin session — and the two
    processes are theatre."""
    trading_cookie = sign("owner@example.com", SECRET, ttl_days=7)
    assert ap.read_session(trading_cookie, SECRET) == (None, "")


def test_a_portal_cookie_is_not_a_trading_app_cookie():
    """The reverse direction. A portal session must not silently become a
    trading session with owner rights on the live engine."""
    from services.session_auth import verify
    portal_cookie = ap.mint_session("owner@example.com", "sid-1", SECRET)
    assert verify(portal_cookie, SECRET) is None


def test_separation_holds_even_when_both_apps_share_one_secret():
    """HUB_ADMIN_SECRET is a hardening step, not the mechanism. Someone who
    never sets it must still get the separation — otherwise the security
    property depends on remembering an optional variable."""
    assert ap.read_session(sign("owner@example.com", SECRET, ttl_days=7), SECRET) == (None, "")
    assert ap.read_session(ap.mint_session("owner@example.com", "s", SECRET), SECRET)[0]


def test_a_token_for_another_purpose_is_refused():
    """The 2FA-pending token is the dangerous one: it is issued BEFORE the
    second factor, so accepting it here would make 2FA optional."""
    pending = sign_scoped("owner@example.com|s", SECRET, purpose="2fa", ttl_s=300)
    assert ap.read_session(pending, SECRET) == (None, "")


def test_the_session_id_is_inside_the_signature():
    """Appended after the signature, a holder could swap in any session id and
    the HMAC would still verify — one admin's cookie claiming another's row."""
    token = ap.mint_session("admin@example.com", "sid-1", SECRET)
    tampered = token.replace("sid-1", "sid-2")
    assert tampered != token
    assert ap.read_session(tampered, SECRET) == (None, "")


def test_a_valid_portal_cookie_round_trips():
    assert ap.read_session(ap.mint_session("admin@example.com", "sid-9", SECRET),
                           SECRET) == ("admin@example.com", "sid-9")


def test_an_expired_portal_cookie_is_refused():
    token = ap.mint_session("admin@example.com", "sid", SECRET, ttl_s=-1)
    assert ap.read_session(token, SECRET) == (None, "")


def test_a_cookie_signed_with_another_secret_is_refused():
    token = ap.mint_session("admin@example.com", "sid", "some-other-secret")
    assert ap.read_session(token, SECRET) == (None, "")


def test_garbage_is_refused_rather_than_raising():
    for junk in ("", "|||", "not-a-token", "a|b", None):
        assert ap.read_session(junk, SECRET) == (None, "")


def test_portal_sessions_are_short_lived_by_default():
    """An idle admin tab is what an attacker with the laptop wants to find."""
    assert ap.DEFAULT_TTL_S <= 4 * 3600


def test_the_admin_secret_falls_back_rather_than_failing_closed(monkeypatch):
    """A portal that refuses to start without a second secret is a portal
    nobody runs — and the purpose scoping already carries the separation."""
    monkeypatch.delenv("HUB_ADMIN_SECRET", raising=False)
    monkeypatch.setenv("HUB_SECRET", "the-main-secret")
    assert ap.admin_secret() == "the-main-secret"
    monkeypatch.setenv("HUB_ADMIN_SECRET", "a-dedicated-secret")
    assert ap.admin_secret() == "a-dedicated-secret"


# ═══════════════════════════════════════════ the front door

@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_a_non_admin_cannot_sign_in_at_all(role):
    """Not "signs in and sees nothing" — refused at the door. A signed-in
    non-admin is one missing check away from acting."""
    allowed, reason = ap.may_sign_in(_u("x@example.com", role))
    assert not allowed
    assert "main application" in reason


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_an_admin_and_the_owner_can_sign_in(role):
    assert ap.may_sign_in(_u("x@example.com", role))[0]


def test_a_disabled_admin_cannot_sign_in():
    """Disabling an account has to close this door too, or "disabled" means
    "disabled everywhere except the most dangerous surface"."""
    assert not ap.may_sign_in(_u("x@example.com", "admin", deleted=True))[0]


def test_an_unknown_account_cannot_sign_in():
    assert not ap.may_sign_in(None)[0]


def test_an_unrecognised_role_cannot_sign_in():
    """Default-deny. A typo in a role column must not become a way in."""
    assert not ap.may_sign_in(_u("x@example.com", "superuser"))[0]


# ═══════════════════════════════════════════ creating accounts

def test_an_admin_cannot_create_an_admin():
    """A minted peer can do everything the minter can — including locking the
    owner out. Only the owner widens the admin set."""
    allowed, reason = ap.may_create(ADMIN, "admin")
    assert not allowed and "owner" in reason


def test_the_owner_can_create_an_admin():
    assert ap.may_create(OWNER, "admin")[0]


def test_nobody_can_create_an_owner():
    """There is exactly one owner, seeded at signup. A second is how a
    deployment ends up with two people who can lock each other out."""
    assert not ap.may_create(OWNER, "owner")[0]
    assert "owner" not in ap.GRANTABLE_ROLES


def test_an_unknown_role_is_refused_rather_than_defaulted():
    """Silently substituting "operator" for a typo grants access nobody asked
    for; refusing makes the operator fix the request."""
    assert not ap.may_create(OWNER, "superuser")[0]


def test_an_operator_cannot_create_anyone():
    assert not ap.may_create(OPERATOR, "viewer")[0]


# ═══════════════════════════════════════════ changing roles

def test_nobody_can_change_their_own_role():
    """Promotion is escalation. Demotion is a lockout you cannot undo from
    inside the portal you just lost access to."""
    for actor in (OWNER, ADMIN):
        allowed, reason = ap.may_set_role(actor, actor, "viewer", EVERYONE)
        assert not allowed and "your own role" in reason


def test_an_admin_cannot_demote_the_owner():
    """The lateral takeover: after this the owner cannot reverse it."""
    assert not ap.may_set_role(ADMIN, OWNER, "viewer", EVERYONE)[0]


def test_an_admin_cannot_demote_another_admin():
    assert not ap.may_set_role(ADMIN, ADMIN2, "viewer", EVERYONE)[0]


def test_an_admin_cannot_promote_someone_to_admin():
    """Reaching upward to grant. Same escalation as creating one, one step
    removed — and it is the step people forget to guard."""
    allowed, reason = ap.may_set_role(ADMIN, OPERATOR, "admin", EVERYONE)
    assert not allowed and "your own level" in reason


def test_an_admin_can_move_an_operator_to_viewer():
    assert ap.may_set_role(ADMIN, OPERATOR, "viewer", EVERYONE)[0]


def test_the_owner_can_promote_an_operator_to_admin():
    assert ap.may_set_role(OWNER, OPERATOR, "admin", EVERYONE)[0]


def test_the_owner_can_demote_an_admin():
    assert ap.may_set_role(OWNER, ADMIN, "operator", EVERYONE)[0]


def test_the_last_owner_cannot_be_demoted_by_anyone():
    """Belt and braces: the self-check and the upward-reach check already
    cover every caller. This is the invariant that actually matters, so it
    should not depend on either of them holding."""
    solo = _u("solo@example.com", "owner")
    other_owner = _u("second@example.com", "owner")
    assert not ap.may_set_role(other_owner, solo, "admin", [solo])[0]


def test_an_operator_cannot_change_any_role():
    assert not ap.may_set_role(OPERATOR, VIEWER, "admin", EVERYONE)[0]


def test_changing_the_role_of_an_unknown_account_is_refused():
    assert not ap.may_set_role(OWNER, None, "viewer", EVERYONE)[0]


# ═══════════════════════════════════════════ disabling and restoring

def test_an_admin_cannot_disable_the_owner():
    assert not ap.may_disable(ADMIN, OWNER, EVERYONE)[0]


def test_an_admin_cannot_disable_another_admin():
    assert not ap.may_disable(ADMIN, ADMIN2, EVERYONE)[0]


def test_an_admin_can_disable_an_operator():
    assert ap.may_disable(ADMIN, OPERATOR, EVERYONE)[0]


def test_disabling_yourself_is_pushed_to_the_account_page():
    """Not a refusal of the intent — a redirection to the door that asks for a
    password. A session cookie proves who you are, not that you are still at
    the keyboard."""
    allowed, reason = ap.may_disable(ADMIN, ADMIN, EVERYONE)
    assert not allowed and "account page" in reason


def test_the_last_active_owner_cannot_be_disabled():
    solo = _u("solo@example.com", "owner")
    second = _u("second@example.com", "owner")
    assert not ap.may_disable(second, solo, [solo])[0]


def test_a_disabled_owner_does_not_count_toward_the_owner_floor():
    """Two owner rows where one is already disabled is one owner. Counting the
    disabled row would let the last live administrator be switched off."""
    live = _u("live@example.com", "owner")
    gone = _u("gone@example.com", "owner", deleted=True)
    assert not ap.may_disable(_u("x@example.com", "owner"), live, [live, gone])[0]


def test_an_admin_cannot_restore_an_admin():
    """Restoring is granting the role back, with extra steps — so it obeys the
    same ceiling as granting it directly."""
    disabled_admin = _u("was-admin@example.com", "admin", deleted=True)
    assert not ap.may_restore(ADMIN, disabled_admin)[0]


def test_the_owner_can_restore_a_disabled_admin():
    assert ap.may_restore(OWNER, _u("was@example.com", "admin", deleted=True))[0]


def test_restoring_an_active_account_is_refused_as_a_no_op():
    assert not ap.may_restore(OWNER, OPERATOR)[0]


# ═══════════════════════════════════════════ revoking sessions

def test_an_admin_can_sign_an_operator_out_everywhere():
    """The first thing an admin reaches for when an account is suspected
    stolen, so it is deliberately the most permissive action here — it removes
    access rather than granting it."""
    assert ap.may_revoke_sessions(ADMIN, OPERATOR)[0]


def test_an_admin_cannot_sign_the_owner_out():
    """Otherwise an admin can disrupt the owner mid-incident-response."""
    assert not ap.may_revoke_sessions(ADMIN, OWNER)[0]


def test_an_admin_can_sign_another_admin_out():
    """Peer level, not above it — and during an incident, waiting for the owner
    to be reachable is the wrong default."""
    assert ap.may_revoke_sessions(ADMIN, ADMIN2)[0]


def test_anyone_can_revoke_their_own_sessions():
    assert ap.may_revoke_sessions(ADMIN, ADMIN)[0]


def test_an_operator_cannot_revoke_anyones_sessions():
    assert not ap.may_revoke_sessions(OPERATOR, VIEWER)[0]


# ═══════════════════════════════════════════ shape of the answers

def test_every_refusal_carries_a_reason():
    """A refusal a user cannot read is a support ticket. This is the part that
    has to be right when someone is locked out."""
    refusals = [
        ap.may_sign_in(VIEWER),
        ap.may_create(ADMIN, "admin"),
        ap.may_set_role(ADMIN, OWNER, "viewer", EVERYONE),
        ap.may_disable(ADMIN, ADMIN, EVERYONE),
        ap.may_restore(ADMIN, _u("x@example.com", "admin", deleted=True)),
        ap.may_revoke_sessions(ADMIN, OWNER),
    ]
    for allowed, reason in refusals:
        assert not allowed
        assert reason and len(reason) > 15, reason
