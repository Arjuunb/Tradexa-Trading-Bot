"""Password reset, email verification and two-factor — the flow logic.

Contract: a reset link works exactly once and only for the account it was
minted for; the reply to a stranger is identical whether or not the account
exists; and nothing ever claims an email was sent that was not.
"""
import pytest

from database.store import SqliteStore
from services import auth_flows as flows
from services import auth_tokens as tok
from services import mailer, totp


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(tmp_path / "hub.db")
    s.create_user("arjun@example.com", "old-password-1", role="owner")
    return s


@pytest.fixture()
def sent(monkeypatch):
    """Capture outbound mail instead of opening an SMTP connection."""
    box = []
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.com")
    monkeypatch.setattr(mailer, "send",
                        lambda to, subject, body: box.append(
                            {"to": to, "subject": subject, "body": body}) or True)
    return box


def _link_token(body: str, path: str) -> str:
    line = next(l for l in body.splitlines() if path in l)
    return line.split("token=", 1)[1].strip()


# ------------------------------------------------------------ password reset

def test_a_reset_link_is_emailed_and_sets_a_new_password(store, sent):
    flows.request_password_reset(store, "arjun@example.com")
    assert len(sent) == 1 and sent[0]["to"] == "arjun@example.com"

    token = _link_token(sent[0]["body"], "/auth/reset-password")
    out = flows.perform_password_reset(store, token, "brand-new-password")
    assert out["ok"] is True
    assert store.authenticate("arjun@example.com", "brand-new-password") is not None
    assert store.authenticate("arjun@example.com", "old-password-1") is None


def test_a_reset_link_works_only_once(store, sent):
    """A link that stays live after use is a standing key sitting in an inbox."""
    flows.request_password_reset(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/reset-password")
    assert flows.perform_password_reset(store, token, "first-password-1")["ok"] is True

    again = flows.perform_password_reset(store, token, "second-password-2")
    assert again["ok"] is False and "already used" in again["error"]
    assert store.authenticate("arjun@example.com", "first-password-1") is not None


def test_issuing_a_second_link_retires_the_first(store, sent):
    """Otherwise an older email keeps working — including one sent to an
    address the account has since moved away from."""
    flows.request_password_reset(store, "arjun@example.com")
    first = _link_token(sent[0]["body"], "/auth/reset-password")
    flows.request_password_reset(store, "arjun@example.com")
    second = _link_token(sent[1]["body"], "/auth/reset-password")

    assert flows.perform_password_reset(store, first, "via-old-link-1")["ok"] is False
    assert flows.perform_password_reset(store, second, "via-new-link-2")["ok"] is True


def test_an_expired_link_is_refused(store, sent, monkeypatch):
    monkeypatch.setattr(tok, "RESET_TTL_S", -1)   # already past when minted
    flows.request_password_reset(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/reset-password")
    out = flows.perform_password_reset(store, token, "too-late-password")
    assert out["ok"] is False and "expired" in out["error"]


def test_a_forged_token_is_refused(store):
    out = flows.perform_password_reset(store, "not-a-real-token", "whatever-1234")
    assert out["ok"] is False


def test_the_new_password_must_pass_the_same_rule_as_signup(store, sent):
    flows.request_password_reset(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/reset-password")
    out = flows.perform_password_reset(store, token, "short")
    assert out["ok"] is False and "8 characters" in out["error"]
    # and the token survives a rejected attempt, so the user can retry
    assert flows.perform_password_reset(store, token, "long-enough-1")["ok"] is True


def test_a_mismatched_confirmation_is_rejected(store, sent):
    flows.request_password_reset(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/reset-password")
    out = flows.perform_password_reset(store, token, "password-one", "password-two")
    assert out["ok"] is False and "do not match" in out["error"]


def test_resetting_a_password_also_confirms_the_address(store, sent):
    """Reading the link proves control of the inbox — which is exactly what
    verification asks for. Asking again would be busywork."""
    flows.request_password_reset(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/reset-password")
    flows.perform_password_reset(store, token, "brand-new-password")
    assert store.get_user("arjun@example.com").email_verified is True


# --------------------------------------------------------- no enumeration

def test_an_unknown_address_gets_the_same_reply_as_a_real_one(store, sent):
    """Any difference here turns the reset form into a membership oracle."""
    real = flows.request_password_reset(store, "arjun@example.com")
    fake = flows.request_password_reset(store, "nobody@example.com")
    assert real["message"] == fake["message"] == flows.GENERIC_RESET_REPLY
    assert real["ok"] == fake["ok"] is True


def test_no_mail_is_sent_for_an_unknown_address(store, sent):
    flows.request_password_reset(store, "nobody@example.com")
    assert sent == []


def test_no_token_is_minted_for_an_unknown_address(store, sent):
    flows.request_password_reset(store, "nobody@example.com")
    assert store._conn.execute("SELECT COUNT(*) AS n FROM auth_tokens").fetchone()["n"] == 0


# ------------------------------------------------- honesty about delivery

def test_an_unconfigured_mailer_says_so_instead_of_pretending(store, monkeypatch):
    """The vague reply protects the stranger. It must not hide a dead mail
    server from the operator, who would otherwise wait forever for a link."""
    monkeypatch.delenv("ALERT_SMTP_HOST", raising=False)
    monkeypatch.delenv("HUB_PUBLIC_URL", raising=False)
    out = flows.request_password_reset(store, "arjun@example.com")
    assert out["delivery"]["available"] is False
    assert "ALERT_SMTP_HOST" in out["delivery"]["note"]
    assert out["message"] == flows.GENERIC_RESET_REPLY      # still no enumeration


def test_a_failed_send_is_reported_not_swallowed(store, monkeypatch):
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.com")
    monkeypatch.setattr(mailer, "send", lambda *a, **k: False)
    out = flows.request_password_reset(store, "arjun@example.com")
    assert out["delivery"]["available"] is False and "send failed" in out["delivery"]["note"]


def test_an_account_with_no_address_is_reported_to_the_operator(store, sent):
    store.create_user("localadmin", "admin-password-1")
    out = flows.request_password_reset(store, "localadmin")
    assert out["delivery"]["available"] is False
    assert "no email address" in out["delivery"]["note"]
    assert out["message"] == flows.GENERIC_RESET_REPLY


# ------------------------------------------------------- email verification

def test_a_verification_link_confirms_the_address(store, sent):
    assert store.get_user("arjun@example.com").email_verified is False
    flows.request_email_verification(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/verify-email")
    assert flows.confirm_email(store, token)["ok"] is True
    assert store.get_user("arjun@example.com").email_verified is True


def test_a_verification_link_works_only_once(store, sent):
    flows.request_email_verification(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/verify-email")
    flows.confirm_email(store, token)
    assert flows.confirm_email(store, token)["ok"] is False


def test_a_reset_token_cannot_be_used_to_confirm_an_email(store, sent):
    """Purposes are separate namespaces. A token minted for one flow must not
    be redeemable in the other."""
    flows.request_password_reset(store, "arjun@example.com")
    token = _link_token(sent[0]["body"], "/auth/reset-password")
    assert flows.confirm_email(store, token)["ok"] is False


def test_verification_is_not_resent_once_confirmed(store, sent):
    flows.request_email_verification(store, "arjun@example.com")
    flows.confirm_email(store, _link_token(sent[0]["body"], "/auth/verify-email"))
    out = flows.request_email_verification(store, "arjun@example.com")
    assert out["already_verified"] is True and len(sent) == 1


# --------------------------------------------------------------- two-factor

def _enable_2fa(store, user="arjun@example.com"):
    setup = flows.begin_totp_setup(store, user)
    out = flows.enable_totp(store, user, totp.code_now(setup["secret"]))
    return setup["secret"], out


def test_setup_stages_a_secret_without_switching_2fa_on(store):
    """Enabling before the user proves they can read a code would lock them out
    with a secret that never reached their phone."""
    setup = flows.begin_totp_setup(store, "arjun@example.com")
    assert setup["ok"] is True and setup["otpauth_uri"].startswith("otpauth://")
    u = store.get_user("arjun@example.com")
    assert u.totp_secret and u.totp_enabled is False


def test_a_correct_code_switches_2fa_on_and_returns_recovery_codes(store):
    _, out = _enable_2fa(store)
    assert out["ok"] is True
    assert len(out["recovery_codes"]) == totp.RECOVERY_COUNT
    assert store.get_user("arjun@example.com").totp_enabled is True


def test_a_wrong_code_leaves_2fa_off(store):
    flows.begin_totp_setup(store, "arjun@example.com")
    out = flows.enable_totp(store, "arjun@example.com", "000000")
    assert out["ok"] is False
    assert store.get_user("arjun@example.com").totp_enabled is False


def test_enabling_without_staging_a_secret_is_refused(store):
    assert flows.enable_totp(store, "arjun@example.com", "123456")["ok"] is False


def test_a_live_code_passes_the_second_factor(store):
    secret, _ = _enable_2fa(store)
    import time
    # a step ahead of the one burned at enrolment
    code = totp.code_now(secret, at=time.time() + totp.STEP_S)
    assert flows.verify_second_factor(store, "arjun@example.com", code)["ok"] is True


def test_a_code_cannot_be_replayed_within_its_window(store):
    """A code stays valid for a full 30 seconds, so without burning the step an
    intercepted code is reusable until the window closes."""
    import time
    secret, _ = _enable_2fa(store)
    at = time.time() + totp.STEP_S
    code = totp.code_now(secret, at=at)
    assert flows.verify_second_factor(store, "arjun@example.com", code)["ok"] is True
    again = flows.verify_second_factor(store, "arjun@example.com", code)
    assert again["ok"] is False and "already used" in again["error"]


def test_a_recovery_code_gets_in_when_the_phone_is_gone(store):
    _, out = _enable_2fa(store)
    code = out["recovery_codes"][0]
    got = flows.verify_second_factor(store, "arjun@example.com", code)
    assert got["ok"] is True and got["method"] == "recovery"
    assert got["recovery_codes_left"] == totp.RECOVERY_COUNT - 1


def test_a_recovery_code_is_single_use(store):
    _, out = _enable_2fa(store)
    code = out["recovery_codes"][0]
    flows.verify_second_factor(store, "arjun@example.com", code)
    assert flows.verify_second_factor(store, "arjun@example.com", code)["ok"] is False


def test_turning_2fa_off_costs_a_password(store):
    """Otherwise a borrowed open session is enough to strip the second factor."""
    _enable_2fa(store)
    assert flows.disable_totp(store, "arjun@example.com", "wrong-password")["ok"] is False
    assert store.get_user("arjun@example.com").totp_enabled is True

    assert flows.disable_totp(store, "arjun@example.com", "old-password-1")["ok"] is True
    assert store.get_user("arjun@example.com").totp_enabled is False


def test_disabling_2fa_clears_the_recovery_codes(store):
    """Leaving them behind would let an old printout re-enter a re-enabled
    account with a secret it never matched."""
    _enable_2fa(store)
    flows.disable_totp(store, "arjun@example.com", "old-password-1")
    assert store.count_unused_recovery_codes("arjun@example.com") == 0


def test_the_second_factor_is_refused_when_2fa_is_off(store):
    assert flows.verify_second_factor(store, "arjun@example.com", "123456")["ok"] is False


def test_status_reports_what_is_actually_configured(store):
    assert flows.totp_status(store, "arjun@example.com")["enabled"] is False
    flows.begin_totp_setup(store, "arjun@example.com")
    assert flows.totp_status(store, "arjun@example.com")["pending_setup"] is True
    _, out = _enable_2fa(store)
    st = flows.totp_status(store, "arjun@example.com")
    assert st["enabled"] is True and st["recovery_codes_left"] == totp.RECOVERY_COUNT
