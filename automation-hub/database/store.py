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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import auth
from database.models import (
    Bot, BotConfig, BotMode, BotRuntime, BotState, RiskRules, User,
)

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_ACTIVE = {BotState.RUNNING, BotState.PAPER, BotState.PAUSED}


def _parse_dt(value):
    """ISO text -> datetime, tolerantly. A malformed timestamp must not break a
    login: the field is informational, and raising here would lock the account
    out over a display value."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _parse_json(value) -> dict:
    """Stored preferences -> dict. Corrupt JSON degrades to empty rather than
    raising, for the same reason: preferences are not worth a failed sign-in."""
    if not value:
        return {}
    try:
        import json
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


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
                    totp_last_step=col("totp_last_step"),
                    full_name=col("full_name"),
                    avatar_url=col("avatar_url"),
                    timezone=col("timezone"),
                    last_login=_parse_dt(col("last_login")),
                    preferences=_parse_json(col("preferences")),
                    deleted_at=_parse_dt(col("deleted_at")))

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
        # A soft-deleted account must not sign in. The password is still
        # verified FIRST and only then discarded, so a deleted account and a
        # wrong password take the same code path and the same time — otherwise
        # a fast rejection tells an attacker the address is real and was
        # deleted, which is exactly the enumeration signal the check exists to
        # avoid leaking.
        deleted = bool(user and user.deleted_at is not None)
        if deleted:
            matched = False
        if os.environ.get("HUB_AUTH_DEBUG") == "1":
            # Diagnostic trail for "my password is right but sign-in fails".
            # Prints the identity looked up and the two booleans that decide the
            # outcome — deliberately NEVER the password and never the stored
            # hash or salt, which would turn a log file into a credential dump.
            print(f"[auth] lookup={_norm_username(username)!r} "
                  f"user_found={user is not None} password_match={matched}"
                  f"{' account_deleted=True' if deleted else ''}",
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

    # ───────────────────────────────────────────────── profile & deletion (0005)
    def update_profile(self, username: str, *, full_name=None, avatar_url=None,
                       timezone=None, preferences=None) -> Optional[User]:
        """Patch semantics: ``None`` means "leave alone", not "clear".

        A PATCH that treated omission as deletion would wipe a user's avatar
        every time they changed their timezone. Clearing a field is done by
        passing an empty string, which is a different thing a caller has to say
        deliberately.
        """
        import json
        sets, args = [], []
        for column, value in (("full_name", full_name), ("avatar_url", avatar_url),
                              ("timezone", timezone)):
            if value is not None:
                sets.append(f"{column}=?")
                args.append(str(value).strip() or None)
        if preferences is not None:
            sets.append("preferences=?")
            args.append(json.dumps(preferences))
        if not sets:
            return self.get_user(username)
        args.append(_norm_username(username))
        with self._lock:
            self._conn.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE username=?", args)
            self._conn.commit()
        return self.get_user(username)

    def touch_login(self, username: str) -> None:
        """Record a successful sign-in. Best-effort: a failure here must never
        turn a valid login into a failed one."""
        try:
            with self._lock:
                self._conn.execute(
                    "UPDATE users SET last_login=? WHERE username=?",
                    (datetime.now(timezone.utc).isoformat(), _norm_username(username)))
                self._conn.commit()
        except Exception:  # noqa: BLE001 — informational field, never fatal
            pass

    def soft_delete_user(self, username: str) -> bool:
        """Mark an account deleted and revoke every session it holds.

        Soft, so an accidental or coerced deletion is recoverable during the
        grace period — and so a support request can prove what was deleted and
        when. The sessions are killed immediately regardless: an account that is
        "deleted but still logged in somewhere" is the worst of both.
        """
        username = _norm_username(username)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE users SET deleted_at=? WHERE username=? AND deleted_at IS NULL",
                (now, username))
            self._conn.execute(
                "UPDATE user_sessions SET revoked_at=?, revoked_by='account_deleted' "
                "WHERE username=? AND revoked_at IS NULL", (now, username))
            self._conn.commit()
            return cur.rowcount > 0

    def restore_user(self, username: str) -> bool:
        """Undo a soft delete within the grace period. Sessions are NOT restored
        — the user signs in again, which is the correct amount of friction after
        an account was deleted."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE users SET deleted_at=NULL WHERE username=?",
                (_norm_username(username),))
            self._conn.commit()
            return cur.rowcount > 0

    def purge_deleted_users(self, older_than_days: int = 30) -> int:
        """Hard-delete accounts past the grace period. Returns how many went.

        Separate from the soft delete and never automatic on the request path:
        irreversible destruction should be a scheduled, auditable job, not a
        side effect of someone clicking a button.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT username FROM users WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,)).fetchall()
            for row in rows:
                name = row["username"]
                # Cascade by hand: SQLite enforces foreign keys only when the
                # pragma is on, and these tables predate it. Explicit deletes
                # are what actually guarantee no orphaned rows survive.
                for table, column in (("user_sessions", "username"),
                                      ("user_settings", "username"),
                                      ("oauth_identities", "username"),
                                      ("auth_tokens", "username")):
                    try:
                        self._conn.execute(f"DELETE FROM {table} WHERE {column}=?", (name,))
                    except Exception:  # noqa: BLE001 — table may not exist yet
                        pass
                self._conn.execute("DELETE FROM users WHERE username=?", (name,))
            self._conn.commit()
            return len(rows)

    # ─────────────────────────────────────────────────────── sessions (0005)
    def create_session(self, username: str, session_id: str, *, ttl_days: int,
                       remembered: bool = False, user_agent: str = "",
                       ip: str = "") -> dict:
        """Record a signed-in device. The cookie carries ``session_id``; this row
        is what that id is checked against, and what revocation acts on."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=max(1, int(ttl_days)))
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO user_sessions"
                "(id, username, created_at, last_seen, expires_at, user_agent, ip,"
                " revoked_at, revoked_by, remembered) VALUES (?,?,?,?,?,?,?,NULL,NULL,?)",
                (session_id, _norm_username(username), now.isoformat(),
                 now.isoformat(), expires.isoformat(),
                 (user_agent or "")[:200], (ip or "")[:64], 1 if remembered else 0))
            self._conn.commit()
        return {"id": session_id, "expires_at": expires.isoformat()}

    def session_is_valid(self, session_id: str) -> bool:
        """Whether this session may still act.

        Unknown ids return True, and that is deliberate: sessions issued before
        this migration have no row, and failing them closed would sign out every
        existing user on deploy. A row that EXISTS and is revoked or expired is
        refused — which is what makes revocation work for everything issued from
        now on.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT revoked_at, expires_at FROM user_sessions WHERE id=?",
                (session_id,)).fetchone()
        if row is None:
            return True
        if row["revoked_at"]:
            return False
        expires = _parse_dt(row["expires_at"])
        return not (expires and expires < datetime.now(timezone.utc))

    def touch_session(self, session_id: str) -> None:
        try:
            with self._lock:
                self._conn.execute(
                    "UPDATE user_sessions SET last_seen=? WHERE id=? AND revoked_at IS NULL",
                    (datetime.now(timezone.utc).isoformat(), session_id))
                self._conn.commit()
        except Exception:  # noqa: BLE001
            pass

    def list_sessions(self, username: str, *, include_revoked: bool = False) -> list[dict]:
        """A user's devices, newest first. What the account page renders."""
        clause = "" if include_revoked else " AND revoked_at IS NULL"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM user_sessions WHERE username=?{clause} "
                "ORDER BY last_seen DESC", (_norm_username(username),)).fetchall()
        return [{"id": r["id"], "created_at": r["created_at"],
                 "last_seen": r["last_seen"], "expires_at": r["expires_at"],
                 "user_agent": r["user_agent"], "ip": r["ip"],
                 "revoked_at": r["revoked_at"], "revoked_by": r["revoked_by"],
                 "remembered": bool(r["remembered"])} for r in rows]

    def revoke_session(self, username: str, session_id: str, *,
                       by: str = "user") -> bool:
        """Revoke ONE session, scoped to its owner.

        The username is part of the WHERE clause, not just a check before it:
        that is what stops a user revoking somebody else's session by guessing
        an id, and it holds even if a caller forgets to authorise first.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE user_sessions SET revoked_at=?, revoked_by=? "
                "WHERE id=? AND username=? AND revoked_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), by, session_id,
                 _norm_username(username)))
            self._conn.commit()
            return cur.rowcount > 0

    def revoke_all_sessions(self, username: str, *, except_id: str = "",
                            by: str = "user") -> int:
        """Sign out everywhere. ``except_id`` keeps the current device signed in.

        Called on password change too: a password reset that leaves an attacker's
        existing session alive has not actually locked them out, which is the
        one thing the user believed they were doing.
        """
        keep = " AND id != ?" if except_id else ""
        args = [datetime.now(timezone.utc).isoformat(), by, _norm_username(username)]
        if except_id:
            args.append(except_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE user_sessions SET revoked_at=?, revoked_by=? "
                f"WHERE username=? AND revoked_at IS NULL{keep}", args)
            self._conn.commit()
            return cur.rowcount

    def purge_expired_sessions(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM user_sessions WHERE expires_at < ?",
                (datetime.now(timezone.utc).isoformat(),))
            self._conn.commit()
            return cur.rowcount

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

    def set_role(self, username: str, role: str) -> bool:
        """Change an account's role. True if a row changed.

        Storage only — WHO may grant WHAT is decided in
        ``services.admin_portal``, because those rules need testing against
        combinations of actor and target that a setter cannot see. The one
        thing enforced here is that the value is a role at all: an unknown
        string would rank below every requirement and silently strip the
        account of access it appeared to keep.
        """
        from services import rbac
        role = (role or "").strip().lower()
        if not rbac.is_valid_role(role):
            return False
        existing = self.get_user(username)
        if existing is None or existing.role == role:
            return False
        with self._lock:
            self._conn.execute("UPDATE users SET role=? WHERE username=?",
                               (role, existing.username))
            self._conn.commit()
        return True

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
