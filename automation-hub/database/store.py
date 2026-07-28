"""SQLite persistence for bots (stdlib ``sqlite3`` — no dependency).

Phase 6. A tiny forward-only migration runner applies ``migrations/*.sql`` in
order and records them in a ``_migrations`` table, so the schema evolves
cleanly. Only the bot *config* + last state is persisted; ephemeral runtime
(metrics, trades, live threads) is re-derived on the next run. Active states
(Running/Paper/Paused) are coerced to Stopped on reload, since background
threads don't survive a restart.
"""
from __future__ import annotations

import json
import os
import threading
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import auth
from database.models import (
    Bot, BotConfig, BotMode, BotRuntime, BotState, RiskRules, User,
)

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_ACTIVE = {BotState.RUNNING, BotState.PAPER, BotState.PAUSED}


def _norm_username(username: str) -> str:
    """The identity as stored: what was typed, minus surrounding whitespace.

    Signup already stripped; login did not, so a single trailing space — the
    kind a password manager or a mobile keyboard adds after an email — made a
    correct password look wrong. Both paths go through here now.
    """
    return (username or "").strip()


class SqliteStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # M-3: this store is shared between request threads and the bot
        # lifecycle. Serialize access with a lock (like every other store) and
        # let concurrent access wait rather than raise "database is locked".
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA busy_timeout=5000")
        # Optional durable mirror for per-user settings (data/settings_store.py).
        # When set, SQLite is the fast local cache and the mirror (Supabase) is
        # the source of truth that survives an ephemeral-disk restart.
        self.settings_mirror = None
        self._migrate()

    # ---------------------------------------------------------- migrations
    def _migrate(self) -> None:
        c = self._conn
        c.execute("CREATE TABLE IF NOT EXISTS _migrations "
                  "(version TEXT PRIMARY KEY, applied_at TEXT)")
        applied = {r["version"] for r in c.execute("SELECT version FROM _migrations")}
        for sql_file in sorted(_MIGRATIONS.glob("*.sql")):
            version = sql_file.stem
            if version in applied:
                continue
            c.executescript(sql_file.read_text(encoding="utf-8"))
            c.execute("INSERT INTO _migrations(version, applied_at) VALUES (?, ?)",
                      (version, datetime.now(timezone.utc).isoformat()))
        c.commit()

    # ---------------------------------------------------------------- CRUD
    def save(self, bot: Bot) -> None:
        cfg = bot.config
        with self._lock:
          self._conn.execute(
            "INSERT OR REPLACE INTO bots"
            "(id, name, strategy, exchange, symbol, timeframe, mode, risk_json,"
            " starting_cash, state, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cfg.id, cfg.name, cfg.strategy, cfg.exchange, cfg.symbol,
             cfg.timeframe, cfg.mode.value, json.dumps(asdict(cfg.risk)),
             cfg.starting_cash, bot.runtime.state.value, cfg.created_at.isoformat()),
          )
          self._conn.commit()

    def delete(self, bot_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
            self._conn.commit()

    def load_all(self) -> list[Bot]:
        out: list[Bot] = []
        for r in self._conn.execute("SELECT * FROM bots ORDER BY created_at"):
            cfg = BotConfig(
                name=r["name"], strategy=r["strategy"], exchange=r["exchange"],
                symbol=r["symbol"], timeframe=r["timeframe"],
                mode=BotMode(r["mode"]), risk=RiskRules(**json.loads(r["risk_json"])),
                starting_cash=r["starting_cash"], id=r["id"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            state = BotState(r["state"])
            if state in _ACTIVE:
                state = BotState.STOPPED      # don't resurrect live threads
            out.append(Bot(config=cfg, runtime=BotRuntime(state=state)))
        return out

    # ------------------------------------------------------------- users (P7)
    def create_user(self, username: str, password: str, role: str = "operator") -> User:
        salt, pw_hash = auth.hash_password(password)
        user = User(username=_norm_username(username), password_hash=pw_hash,
                    salt=salt, role=role)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO users"
                "(username, password_hash, salt, role, created_at) VALUES (?,?,?,?,?)",
                (user.username, user.password_hash, user.salt, user.role,
                 user.created_at.isoformat()),
            )
            self._conn.commit()
        return user

    @staticmethod
    def _row_to_user(r) -> User:
        keys = r.keys()

        def col(name, default=None):
            # Tolerates a row read before 0004 applied (or a SELECT of older
            # columns) instead of raising IndexError deep inside a login.
            return r[name] if name in keys else default

        return User(username=r["username"], password_hash=r["password_hash"],
                    salt=r["salt"], role=r["role"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                    email=col("email"),
                    email_verified=bool(col("email_verified", 0)),
                    totp_secret=col("totp_secret"),
                    totp_enabled=bool(col("totp_enabled", 0)),
                    totp_last_step=col("totp_last_step"))

    def get_user(self, username: str) -> User | None:
        username = _norm_username(username)
        if not username:
            return None
        # Exact match first, so a hub that already holds both "Bob" and "bob"
        # keeps resolving each to itself. Only when that misses do we retry
        # case-insensitively: nobody remembers whether they capitalised their
        # email at signup, and "Arjun@Gmail.com" is not a different person from
        # "arjun@gmail.com".
        r = self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if r is None:
            r = self._conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,)).fetchone()
        return self._row_to_user(r) if r is not None else None

    def list_users(self) -> list[User]:
        return [self._row_to_user(r)
                for r in self._conn.execute("SELECT * FROM users ORDER BY created_at")]

    def count_users(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get_user(username)
        matched = bool(user and auth.verify_password(
            password, user.salt, user.password_hash))
        if os.environ.get("HUB_AUTH_DEBUG") == "1":
            # Diagnostic trail for "my password is right but sign-in fails".
            # Prints the identity looked up and the two booleans that decide the
            # outcome — deliberately NEVER the password and never the stored
            # hash or salt, which would turn a log file into a credential dump.
            print(f"[auth] lookup={_norm_username(username)!r} "
                  f"user_found={user is not None} password_match={matched}",
                  flush=True)
        return user if matched else None

    def auth_failure_reason(self, username: str) -> str:
        """Why a sign-in failed, in terms someone can act on. Only meaningful
        after ``authenticate`` returned None.

            "no-such-user"  — nothing in the users table matches that identity
            "bad-password"  — the account exists, the password did not match
        """
        return "no-such-user" if self.get_user(username) is None else "bad-password"

    def seed_admin(self, username: str, password: str) -> None:
        """Create the first admin from config if there are no users yet."""
        if self.count_users() == 0:
            self.create_user(username, password, role="admin")

    # ------------------------------------------------------- email identity
    def find_by_email(self, email: str) -> User | None:
        """Resolve a contact address to an account.

        Two places to look, because most accounts here signed up with their
        email AS the username and so have never set the email column. Matching
        only one of them would make password reset fail for exactly the
        accounts most likely to need it.
        """
        email = _norm_username(email)
        if not email:
            return None
        r = self._conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
        if r is not None:
            return self._row_to_user(r)
        return self.get_user(email)

    def set_email(self, username: str, email: str, *, verified: bool = False) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE users SET email=?, email_verified=? WHERE username=?",
                (_norm_username(email), 1 if verified else 0, user.username))
            self._conn.commit()

    def mark_email_verified(self, username: str) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            # Backfill the column for accounts whose username IS their email —
            # otherwise the flag lands on a row with nothing to point at.
            self._conn.execute(
                "UPDATE users SET email_verified=1, email=COALESCE(email, ?) "
                "WHERE username=?", (user.contact_email, user.username))
            self._conn.commit()

    # --------------------------------------------------- single-use tokens
    def put_auth_token(self, username: str, token_hash: str, purpose: str,
                       expires_at: str) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            # One live token per purpose: issuing a second reset link must
            # retire the first, or an old email stays a working key.
            self._conn.execute(
                "DELETE FROM auth_tokens WHERE username=? AND purpose=?",
                (user.username, purpose))
            self._conn.execute(
                "INSERT INTO auth_tokens(token_hash, username, purpose, expires_at,"
                " used_at, created_at) VALUES (?,?,?,?,NULL,?)",
                (token_hash, user.username, purpose, expires_at,
                 datetime.now(timezone.utc).isoformat()))
            self._conn.commit()

    def redeem_auth_token(self, token_hash: str, purpose: str) -> Optional[str]:
        """Consume a token, returning the username it belongs to, or None.

        Expiry and single-use are enforced here rather than at issue time, and
        the row is marked used inside the same lock as the check — otherwise
        two requests arriving together could both redeem the same token.
        """
        from services.auth_tokens import is_expired
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM auth_tokens WHERE token_hash=? AND purpose=?",
                (token_hash, purpose)).fetchone()
            if r is None or r["used_at"] is not None or is_expired(r["expires_at"]):
                return None
            self._conn.execute("UPDATE auth_tokens SET used_at=? WHERE token_hash=?",
                               (datetime.now(timezone.utc).isoformat(), token_hash))
            self._conn.commit()
            return r["username"]

    def purge_expired_tokens(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM auth_tokens WHERE expires_at < ?",
                (datetime.now(timezone.utc).isoformat(),))
            self._conn.commit()
            return cur.rowcount or 0

    # ------------------------------------------------------------- two-factor
    def set_totp_secret(self, username: str, secret: Optional[str]) -> None:
        """Stage a secret without enabling 2FA. Enabling before the user has
        proved they can produce a code would lock them out of their own
        account with a secret they never successfully scanned."""
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE users SET totp_secret=?, totp_enabled=0, totp_last_step=NULL "
                "WHERE username=?", (secret, user.username))
            self._conn.commit()

    def enable_totp(self, username: str, recovery_hashes: list[str]) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            self._conn.execute("UPDATE users SET totp_enabled=1 WHERE username=?",
                               (user.username,))
            self._conn.execute("DELETE FROM totp_recovery WHERE username=?",
                               (user.username,))
            now = datetime.now(timezone.utc).isoformat()
            self._conn.executemany(
                "INSERT OR REPLACE INTO totp_recovery(code_hash, username, used_at,"
                " created_at) VALUES (?,?,NULL,?)",
                [(h, user.username, now) for h in recovery_hashes])
            self._conn.commit()

    def disable_totp(self, username: str) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE users SET totp_enabled=0, totp_secret=NULL, totp_last_step=NULL "
                "WHERE username=?", (user.username,))
            self._conn.execute("DELETE FROM totp_recovery WHERE username=?",
                               (user.username,))
            self._conn.commit()

    def record_totp_step(self, username: str, step: int) -> bool:
        """Burn a TOTP step. False if it was already used — the replay guard.

        The read and the write share one lock, so two requests racing with the
        same intercepted code cannot both win.
        """
        user = self.get_user(username)
        if user is None:
            return False
        with self._lock:
            r = self._conn.execute(
                "SELECT totp_last_step FROM users WHERE username=?",
                (user.username,)).fetchone()
            last = r["totp_last_step"] if r else None
            if last is not None and step <= last:
                return False
            self._conn.execute("UPDATE users SET totp_last_step=? WHERE username=?",
                               (step, user.username))
            self._conn.commit()
            return True

    def consume_recovery_code(self, username: str, code_hash: str) -> bool:
        user = self.get_user(username)
        if user is None:
            return False
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM totp_recovery WHERE code_hash=? AND username=?",
                (code_hash, user.username)).fetchone()
            if r is None or r["used_at"] is not None:
                return False
            self._conn.execute(
                "UPDATE totp_recovery SET used_at=? WHERE code_hash=?",
                (datetime.now(timezone.utc).isoformat(), code_hash))
            self._conn.commit()
            return True

    def count_unused_recovery_codes(self, username: str) -> int:
        user = self.get_user(username)
        if user is None:
            return 0
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM totp_recovery WHERE username=? AND used_at IS NULL",
            (user.username,)).fetchone()["n"]

    # ------------------------------------------------------------------ OAuth
    def link_oauth(self, provider: str, subject: str, username: str,
                   email: Optional[str] = None) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO oauth_identities(provider, subject, username,"
                " email, created_at) VALUES (?,?,?,?,?)",
                (provider, str(subject), user.username, email,
                 datetime.now(timezone.utc).isoformat()))
            self._conn.commit()

    def find_by_oauth(self, provider: str, subject: str) -> User | None:
        r = self._conn.execute(
            "SELECT username FROM oauth_identities WHERE provider=? AND subject=?",
            (provider, str(subject))).fetchone()
        return self.get_user(r["username"]) if r else None

    def list_oauth_links(self, username: str) -> list[dict]:
        user = self.get_user(username)
        if user is None:
            return []
        return [{"provider": r["provider"], "email": r["email"],
                 "linked_at": r["created_at"]}
                for r in self._conn.execute(
                    "SELECT * FROM oauth_identities WHERE username=? ORDER BY created_at",
                    (user.username,))]

    def unlink_oauth(self, provider: str, username: str) -> None:
        user = self.get_user(username)
        if user is None:
            return
        with self._lock:
            self._conn.execute(
                "DELETE FROM oauth_identities WHERE provider=? AND username=?",
                (provider, user.username))
            self._conn.commit()

    def set_password(self, username: str, new_password: str) -> None:
        # Resolve through get_user so a case- or whitespace-variant of the
        # stored username updates the real row instead of matching nothing and
        # silently leaving the old password in place.
        existing = self.get_user(username)
        if existing is None:
            return
        salt, pw_hash = auth.hash_password(new_password)
        with self._lock:
            self._conn.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?",
                               (pw_hash, salt, existing.username))
            self._conn.commit()

    # -------------------------------------------------- per-user settings
    def _sqlite_get_settings(self, username: str, namespace: str) -> dict:
        r = self._conn.execute(
            "SELECT data FROM user_settings WHERE username=? AND namespace=?",
            (username, namespace)).fetchone()
        if r is None:
            return {}
        try:
            return json.loads(r["data"]) or {}
        except Exception:  # noqa: BLE001 — corrupt blob -> behave as empty
            return {}

    def _sqlite_set_settings(self, username: str, namespace: str, data: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO user_settings(username, namespace, data, updated_at) "
                "VALUES (?,?,?,?)",
                (username, namespace, json.dumps(data),
                 datetime.now(timezone.utc).isoformat()))
            self._conn.commit()

    def get_user_settings(self, username: str, namespace: str) -> dict:
        """The user's saved workspace blob for one namespace ({} if none).

        Reads the local SQLite cache first; on a miss (e.g. after an
        ephemeral-disk restart) it pulls from the durable mirror and backfills
        the cache, so a login always restores real settings instead of defaults."""
        local = self._sqlite_get_settings(username, namespace)
        if local:
            return local
        if self.settings_mirror is not None:
            remote = self.settings_mirror.get(username, namespace)
            if remote:
                self._sqlite_set_settings(username, namespace, remote)   # warm the cache
                return remote
        return {}

    def set_user_settings(self, username: str, namespace: str, data: dict) -> None:
        self._sqlite_set_settings(username, namespace, data)
        if self.settings_mirror is not None:
            self.settings_mirror.set(username, namespace, data)          # durable write

    def delete_user_settings(self, username: str, namespace: str | None = None) -> None:
        """Explicit reset only — called from the user's own Reset actions."""
        with self._lock:
            if namespace is None:
                self._conn.execute("DELETE FROM user_settings WHERE username=?", (username,))
            else:
                self._conn.execute(
                    "DELETE FROM user_settings WHERE username=? AND namespace=?",
                    (username, namespace))
            self._conn.commit()
        if self.settings_mirror is not None:
            self.settings_mirror.delete(username, namespace)

    def close(self) -> None:
        self._conn.close()
