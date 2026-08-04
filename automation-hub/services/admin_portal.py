"""Authorisation policy and session tokens for the separated admin portal.

The portal is a **second ASGI app**, run as its own process on its own port, so
that a compromise of the trading app is not automatically a compromise of user
management. That separation only means something if the two apps cannot accept
each other's credentials — otherwise it is two front doors onto one lock.

Two mechanisms, and both are load-bearing:

1. **Domain-separated tokens.** Portal cookies are signed with a purpose-scoped
   key (``session_auth.sign_scoped``), so a trading-app session cookie is
   arithmetically unable to validate here *even when both apps share
   HUB_SECRET*. Setting ``HUB_ADMIN_SECRET`` separates the raw key as well, but
   forgetting to set it does not collapse the separation.

2. **Policy in one pure module.** Every "may X do Y to Z" question is answered
   here, not inside a route handler, so the rules can be tested exhaustively
   without HTTP and cannot drift between the page and the form that submits to
   it.

Everything returns ``(allowed, reason)`` rather than raising or returning a bare
bool: a refusal a user cannot read is a support ticket, and the reason is the
part that has to be right when someone is locked out.

**Deliberately absent: setting another user's password.** An admin who can do
that can sign in as anyone and act as them, which makes every audit record
deniable. Recovery goes through the user's own email reset, and an admin who
needs to break the glass has the emergency `.env` credentials.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional, Sequence, Tuple

from services import rbac
from services.session_auth import sign_scoped, verify_scoped

#: Purpose string bound into the signing key. Changing it invalidates every
#: portal cookie, which is the correct response to a suspected key compromise.
PURPOSE = "admin_portal"

#: Portal sessions are short by design. This is not a place to stay signed in:
#: an idle admin tab is the thing an attacker with the laptop wants to find.
DEFAULT_TTL_S = 60 * 60

#: Roles the portal will hand out. `owner` is absent on purpose — there is
#: exactly one, seeded at signup, and minting a second is how a deployment ends
#: up with two people who can lock each other out.
GRANTABLE_ROLES: Tuple[str, ...] = ("viewer", "operator", "admin")

Decision = Tuple[bool, str]


def admin_secret() -> str:
    """The portal's signing secret.

    Falls back to ``HUB_SECRET`` so the portal works on day one, because a
    portal that refuses to start until a second secret is set is a portal nobody
    runs. The purpose scoping above means the fallback is still not
    interchangeable with a trading-app cookie.
    """
    return (os.environ.get("HUB_ADMIN_SECRET")
            or os.environ.get("HUB_SECRET") or "dev-insecure-secret")


# ─────────────────────────────────────────────────────────────────── tokens

def mint_session(username: str, session_id: str, secret: str,
                 ttl_s: int = DEFAULT_TTL_S) -> str:
    """A portal cookie for ``username``, bound to a revocable session row.

    The session id lives inside the signed subject rather than after the
    signature: appended, a holder could swap in any id and the HMAC would still
    verify, which is the same hole the trading app's cookie was built to avoid.
    """
    return sign_scoped(f"{username}|{session_id}", secret,
                       purpose=PURPOSE, ttl_s=ttl_s)


def read_session(token: str, secret: str) -> Tuple[Optional[str], str]:
    """``(username, session_id)`` for an authentic portal cookie, else
    ``(None, "")``. A trading-app cookie always lands here."""
    subject = verify_scoped(token or "", secret, purpose=PURPOSE)
    if subject is None:
        return None, ""
    # rsplit: usernames are emails and cannot contain "|", but splitting from
    # the right keeps this correct even if one ever did.
    username, _, session_id = subject.rpartition("|")
    if not username:                      # no separator — not a portal subject
        return None, ""
    return username, session_id


# ────────────────────────────────────────────────────────────────── policy

def _rank(user) -> int:
    return rbac.rank(getattr(user, "role", ""))


def _active_owners(users: Iterable) -> list:
    return [u for u in users
            if getattr(u, "role", "") == "owner" and getattr(u, "active", False)]


def may_sign_in(user) -> Decision:
    """Who is allowed through the portal's front door at all.

    Checked before the password, and again on every request: a role revoked
    while someone is signed in has to take effect on their next click, not when
    their cookie expires.
    """
    if user is None:
        return False, "No such account"
    if not getattr(user, "active", False):
        return False, "That account is disabled"
    if not rbac.can(getattr(user, "role", ""), "manage_users"):
        return False, ("This portal is for administrators. Your account signs in "
                       "at the main application")
    return True, ""


def may_create(actor, role: str) -> Decision:
    """Creating an account, and choosing what it starts as."""
    role = (role or "").strip().lower()
    if not rbac.can(getattr(actor, "role", ""), "manage_users"):
        return False, "Only administrators can create accounts"
    if role not in GRANTABLE_ROLES:
        return False, f"Role must be one of: {', '.join(GRANTABLE_ROLES)}"
    # Escalation guard: an admin who could mint admins could mint a peer, and a
    # peer can do everything they can — including locking the owner out.
    if role == "admin" and _rank(actor) < rbac.rank("owner"):
        return False, "Only the owner can create administrators"
    return True, ""


def may_set_role(actor, target, new_role: str, users: Sequence) -> Decision:
    """Changing an existing account's role — the portal's sharpest edge.

    Four separate ways this goes wrong, so four separate checks.
    """
    new_role = (new_role or "").strip().lower()
    if not rbac.can(getattr(actor, "role", ""), "manage_users"):
        return False, "Only administrators can change roles"
    if target is None:
        return False, "No such account"
    if new_role not in GRANTABLE_ROLES:
        return False, f"Role must be one of: {', '.join(GRANTABLE_ROLES)}"

    # 1. Self. Promotion is escalation; demotion is a lockout you cannot undo
    #    from inside the portal you just lost access to.
    if getattr(actor, "username", None) == getattr(target, "username", None):
        return False, "You cannot change your own role"

    # 2. Reaching upward. An admin demoting an owner — or another admin — is
    #    a lateral takeover: the target loses the ability to reverse it.
    if _rank(target) >= _rank(actor):
        return False, ("You cannot change the role of an account at or above "
                       "your own level")

    # 3. Granting upward. Nobody hands out privilege they do not hold.
    if rbac.rank(new_role) >= _rank(actor):
        return False, "You cannot grant a role at or above your own level"

    # 4. The last owner. Belt and braces — rule 2 already blocks an admin, and
    #    rule 1 blocks the owner themselves, but this is the invariant that
    #    actually matters and it should not depend on the others holding.
    if getattr(target, "role", "") == "owner" and len(_active_owners(users)) <= 1:
        return False, "This is the only owner — the deployment would have no administrator"
    return True, ""


def may_disable(actor, target, users: Sequence) -> Decision:
    """Disabling (soft-deleting) an account."""
    if not rbac.can(getattr(actor, "role", ""), "manage_users"):
        return False, "Only administrators can disable accounts"
    if target is None:
        return False, "No such account"
    if getattr(actor, "username", None) == getattr(target, "username", None):
        return False, ("You cannot disable your own account here — use the "
                       "account page, which asks for your password")
    if _rank(target) >= _rank(actor):
        return False, ("You cannot disable an account at or above your own level")
    if getattr(target, "role", "") == "owner" and len(_active_owners(users)) <= 1:
        return False, "This is the only owner — the deployment would have no administrator"
    return True, ""


def may_restore(actor, target) -> Decision:
    """Restoring a soft-deleted account.

    Restoring an admin is a privilege grant with extra steps, so it obeys the
    same ceiling as granting the role directly.
    """
    if not rbac.can(getattr(actor, "role", ""), "manage_users"):
        return False, "Only administrators can restore accounts"
    if target is None:
        return False, "No such account"
    if getattr(target, "active", False):
        return False, "That account is already active"
    if _rank(target) >= _rank(actor):
        return False, "You cannot restore an account at or above your own level"
    return True, ""


def may_revoke_sessions(actor, target) -> Decision:
    """Signing another account out of every device.

    Deliberately more permissive than the others: it takes privilege away
    rather than granting it, and "sign that person out NOW" is the first thing
    an admin reaches for when an account is suspected stolen. Still refuses to
    reach upward, so an admin cannot use it to disrupt an owner mid-response.
    """
    if not rbac.can(getattr(actor, "role", ""), "manage_users"):
        return False, "Only administrators can revoke sessions"
    if target is None:
        return False, "No such account"
    if (getattr(actor, "username", None) != getattr(target, "username", None)
            and _rank(target) > _rank(actor)):
        return False, "You cannot revoke sessions for an account above your own level"
    return True, ""
