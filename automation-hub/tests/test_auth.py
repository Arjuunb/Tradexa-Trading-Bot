"""Phase 7: password hashing + multi-user accounts."""
import auth
from database.store import SqliteStore


# ------------------------------------------------------------------ hashing
def test_hash_verify_roundtrip():
    salt, h = auth.hash_password("s3cret")
    assert auth.verify_password("s3cret", salt, h)
    assert not auth.verify_password("wrong", salt, h)


def test_passwords_are_salted_and_not_plaintext():
    s1, h1 = auth.hash_password("same")
    s2, h2 = auth.hash_password("same")
    assert s1 != s2 and h1 != h2          # unique salts -> different hashes
    assert "same" not in h1               # not stored in the clear


# -------------------------------------------------------------- user store
def test_create_authenticate_and_roles(tmp_path):
    store = SqliteStore(tmp_path / "hub.db")
    store.create_user("alice", "pw123", role="operator")
    assert store.authenticate("alice", "pw123").username == "alice"
    assert store.authenticate("alice", "nope") is None
    assert store.authenticate("ghost", "x") is None
    assert store.get_user("alice").role == "operator"
    assert not store.get_user("alice").is_admin


def test_stored_password_is_hashed(tmp_path):
    store = SqliteStore(tmp_path / "hub.db")
    store.create_user("bob", "plaintext")
    row = store._conn.execute(
        "SELECT password_hash FROM users WHERE username='bob'").fetchone()
    assert row["password_hash"] != "plaintext"
    assert len(row["password_hash"]) == 64       # sha256 hex digest


def test_seed_admin_is_idempotent_and_admin(tmp_path):
    db = tmp_path / "hub.db"
    store = SqliteStore(db)
    store.seed_admin("admin", "admin")
    store.seed_admin("admin", "admin")           # second call must no-op
    assert store.count_users() == 1
    assert store.get_user("admin").is_admin
    assert store.authenticate("admin", "admin") is not None


def test_seed_admin_skips_when_users_exist(tmp_path):
    store = SqliteStore(tmp_path / "hub.db")
    store.create_user("someone", "pw")
    store.seed_admin("admin", "admin")           # users already exist -> skip
    assert store.get_user("admin") is None
