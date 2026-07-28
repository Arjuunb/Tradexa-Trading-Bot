"""Sign-in identity resolution.

Contract: the identity someone types resolves to the account they created, and
when it does not, the failure says which of the two things went wrong. These
are regression tests for a real report — "correct username and password, still
Invalid credentials" — where signup stripped whitespace and login did not, and
where the lookup was case-sensitive against an email nobody capitalises twice
the same way.
"""
import pytest

from database.store import SqliteStore


@pytest.fixture()
def store(tmp_path):
    return SqliteStore(tmp_path / "hub.db")


# ------------------------------------------------------------ the hash itself

def test_the_stored_secret_is_a_pbkdf2_hash_not_the_password(store):
    """The comparison is hash-vs-hash. If this ever stored the password itself,
    every check below would still pass while the database leaked credentials."""
    u = store.create_user("arjun@example.com", "correct horse battery")
    assert u.password_hash != "correct horse battery"
    assert len(u.password_hash) == 64 and len(u.salt) == 32  # sha256 hex, 16-byte salt


def test_the_right_password_authenticates_and_the_wrong_one_does_not(store):
    store.create_user("arjun@example.com", "correct horse battery")
    assert store.authenticate("arjun@example.com", "correct horse battery") is not None
    assert store.authenticate("arjun@example.com", "wrong") is None


# --------------------------------------------------------------- whitespace

def test_a_trailing_space_from_a_password_manager_still_signs_in(store):
    """Signup stripped the username, login did not — so the row was stored
    clean and looked up dirty, and the lookup missed."""
    store.create_user("arjun@example.com", "pw-12345678")
    assert store.authenticate("arjun@example.com ", "pw-12345678") is not None
    assert store.authenticate("  arjun@example.com", "pw-12345678") is not None


def test_signup_stores_the_stripped_identity(store):
    assert store.create_user("  arjun@example.com  ", "pw-12345678").username == "arjun@example.com"


# ---------------------------------------------------------------- case

def test_an_email_capitalised_differently_is_the_same_person(store):
    store.create_user("Arjun@Example.com", "pw-12345678")
    assert store.authenticate("arjun@example.com", "pw-12345678") is not None
    assert store.authenticate("ARJUN@EXAMPLE.COM", "pw-12345678") is not None


def test_an_exact_match_still_wins_over_a_case_variant(store):
    """A hub that already holds both spellings must keep resolving each to
    itself — case-insensitivity is a fallback, not an override."""
    store.create_user("Bob", "pw-bob-1234")
    store.create_user("bob", "pw-bob-5678")
    assert store.authenticate("Bob", "pw-bob-1234") is not None
    assert store.authenticate("bob", "pw-bob-5678") is not None
    assert store.authenticate("Bob", "pw-bob-5678") is None


def test_the_resolved_user_carries_the_stored_spelling(store):
    """The session is signed with this name, and per-user settings are keyed by
    it — returning the typed spelling would hand someone an empty namespace."""
    store.create_user("Arjun@Example.com", "pw-12345678")
    assert store.authenticate("arjun@example.com", "pw-12345678").username == "Arjun@Example.com"


def test_a_password_reset_finds_the_row_through_a_case_variant(store):
    store.create_user("Arjun@Example.com", "pw-old-12345")
    store.set_password("arjun@example.com", "pw-new-12345")
    assert store.authenticate("Arjun@Example.com", "pw-new-12345") is not None


def test_resetting_a_password_for_nobody_changes_nothing(store):
    store.create_user("arjun@example.com", "pw-12345678")
    store.set_password("someone-else", "pw-attacker")
    assert store.authenticate("arjun@example.com", "pw-12345678") is not None


# ------------------------------------------------------------- empty input

def test_an_empty_identity_matches_no_one(store):
    store.create_user("arjun@example.com", "pw-12345678")
    assert store.get_user("") is None and store.get_user("   ") is None


# --------------------------------------------------- why the sign-in failed

def test_a_wrong_password_is_reported_as_a_wrong_password(store):
    store.create_user("arjun@example.com", "pw-12345678")
    assert store.auth_failure_reason("arjun@example.com") == "bad-password"


def test_a_missing_account_is_not_reported_as_a_wrong_password(store):
    """The distinction is the whole point: "Invalid credentials" sends someone
    to re-check a password that was never the problem."""
    assert store.auth_failure_reason("ghost@example.com") == "no-such-user"


# ------------------------------------------------------- diagnostic logging

def test_debug_logging_is_off_unless_asked_for(store, capsys, monkeypatch):
    monkeypatch.delenv("HUB_AUTH_DEBUG", raising=False)
    store.create_user("arjun@example.com", "pw-12345678")
    store.authenticate("arjun@example.com", "nope")
    assert "[auth]" not in capsys.readouterr().out


def test_debug_logging_shows_lookup_found_and_match(store, capsys, monkeypatch):
    monkeypatch.setenv("HUB_AUTH_DEBUG", "1")
    store.create_user("arjun@example.com", "pw-12345678")

    store.authenticate("  arjun@example.com ", "wrong-password")
    out = capsys.readouterr().out
    assert "lookup='arjun@example.com'" in out          # normalised, as queried
    assert "user_found=True" in out and "password_match=False" in out

    store.authenticate("ghost@example.com", "pw-12345678")
    out = capsys.readouterr().out
    assert "user_found=False" in out and "password_match=False" in out

    store.authenticate("arjun@example.com", "pw-12345678")
    assert "password_match=True" in capsys.readouterr().out


def test_debug_logging_never_prints_the_password_or_the_hash(store, capsys, monkeypatch):
    """A diagnostic that dumps credentials into a log file is a bigger bug than
    the one it was added to find."""
    monkeypatch.setenv("HUB_AUTH_DEBUG", "1")
    u = store.create_user("arjun@example.com", "super-secret-pw")
    store.authenticate("arjun@example.com", "super-secret-pw")
    out = capsys.readouterr().out
    assert "super-secret-pw" not in out
    assert u.password_hash not in out and u.salt not in out


# ------------------------------------------------------------- the routes

@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import app as hub_app
    monkeypatch.setattr(hub_app, "store", SqliteStore(tmp_path / "hub.db"))
    hub_app.store.create_user("Arjun@Example.com", "pw-12345678", role="owner")
    hub_app._sessions.clear()
    return TestClient(hub_app.app, follow_redirects=False)


def test_form_login_accepts_the_email_however_it_is_typed(client):
    import app as hub_app
    for typed in ("Arjun@Example.com", "arjun@example.com", " ARJUN@example.com "):
        client.cookies.clear()
        r = client.post("/login", data={"username": typed, "password": "pw-12345678"})
        assert r.status_code == 303 and r.headers["location"] == "/", typed
        # the session carries the stored spelling, so per-user settings resolve
        raw = r.cookies[hub_app.COOKIE].strip('"')   # an email contains '@', so
        assert hub_app._verify_session(raw) == "Arjun@Example.com"  # the client quotes it


def test_the_session_cookie_survives_the_round_trip_for_an_email_username(client):
    """An email contains '@', which makes clients quote the cookie value. The
    server must still read it back — otherwise sign-in "succeeds" and the very
    next request bounces to /login."""
    r = client.post("/login", data={"username": "arjun@example.com",
                                    "password": "pw-12345678"})
    assert r.status_code == 303
    assert client.get("/").status_code == 200      # not redirected back to /login


def test_form_login_says_invalid_credentials_only_for_a_wrong_password(client):
    r = client.post("/login", data={"username": "arjun@example.com", "password": "nope"})
    assert "Invalid+credentials" in r.headers["location"]


def test_form_login_says_no_such_account_when_there_is_none(client):
    r = client.post("/login", data={"username": "ghost@example.com", "password": "nope"})
    loc = r.headers["location"]
    assert "Invalid+credentials" not in loc
    assert "No+account" in loc


def test_json_login_returns_the_stored_username(client):
    r = client.post("/auth/login",
                    data={"username": " arjun@EXAMPLE.com ", "password": "pw-12345678"})
    assert r.status_code == 200
    assert r.json()["user"] == "Arjun@Example.com"


def test_json_login_still_401s_on_a_wrong_password(client):
    r = client.post("/auth/login",
                    data={"username": "arjun@example.com", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"


# --------------------------------------------------- durability disclosure

def test_the_login_page_warns_when_accounts_do_not_survive_a_redeploy(client, monkeypatch):
    """The reason a correct password stops working on ephemeral storage is that
    the account is gone. The sign-in page is the only place the person locked
    out will look."""
    import app as hub_app
    monkeypatch.setattr(hub_app.webhook_api, "storage_assessment",
                        lambda: {"local_durable": False})
    body = client.get("/login").text
    assert "erased on every redeploy" in body and "HUB_DATA_DIR" in body


def test_a_durable_hub_shows_no_storage_warning(client, monkeypatch):
    import app as hub_app
    monkeypatch.setattr(hub_app.webhook_api, "storage_assessment",
                        lambda: {"local_durable": True})
    assert "erased on every redeploy" not in client.get("/login").text


def test_a_missing_account_on_ephemeral_storage_explains_why(client, monkeypatch):
    import app as hub_app
    monkeypatch.setattr(hub_app.webhook_api, "storage_assessment",
                        lambda: {"local_durable": False})
    loc = client.post("/login", data={"username": "ghost@example.com",
                                      "password": "nope"}).headers["location"]
    assert "ephemeral" in loc and "HUB_DATA_DIR" in loc


def test_a_wrong_password_never_blames_storage(client, monkeypatch):
    """The account is right there. Pointing at the disk would send someone to
    fix infrastructure over a typo."""
    import app as hub_app
    monkeypatch.setattr(hub_app.webhook_api, "storage_assessment",
                        lambda: {"local_durable": False})
    loc = client.post("/login", data={"username": "arjun@example.com",
                                      "password": "nope"}).headers["location"]
    assert "Invalid+credentials" in loc and "ephemeral" not in loc
