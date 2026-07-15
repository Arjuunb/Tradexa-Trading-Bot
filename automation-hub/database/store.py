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
import threading
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import auth
from database.models import (
    Bot, BotConfig, BotMode, BotRuntime, BotState, RiskRules, User,
)

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_ACTIVE = {BotState.RUNNING, BotState.PAPER, BotState.PAUSED}


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
        user = User(username=username, password_hash=pw_hash, salt=salt, role=role)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO users"
                "(username, password_hash, salt, role, created_at) VALUES (?,?,?,?,?)",
                (user.username, user.password_hash, user.salt, user.role,
                 user.created_at.isoformat()),
            )
            self._conn.commit()
        return user

    def get_user(self, username: str) -> User | None:
        r = self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if r is None:
            return None
        return User(username=r["username"], password_hash=r["password_hash"],
                    salt=r["salt"], role=r["role"],
                    created_at=datetime.fromisoformat(r["created_at"]))

    def list_users(self) -> list[User]:
        return [User(username=r["username"], password_hash=r["password_hash"],
                     salt=r["salt"], role=r["role"],
                     created_at=datetime.fromisoformat(r["created_at"]))
                for r in self._conn.execute("SELECT * FROM users ORDER BY created_at")]

    def count_users(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get_user(username)
        if user and auth.verify_password(password, user.salt, user.password_hash):
            return user
        return None

    def seed_admin(self, username: str, password: str) -> None:
        """Create the first admin from config if there are no users yet."""
        if self.count_users() == 0:
            self.create_user(username, password, role="admin")

    def set_password(self, username: str, new_password: str) -> None:
        salt, pw_hash = auth.hash_password(new_password)
        with self._lock:
            self._conn.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?",
                               (pw_hash, salt, username))
            self._conn.commit()

    # -------------------------------------------------- per-user settings
    def get_user_settings(self, username: str, namespace: str) -> dict:
        """The user's saved workspace blob for one namespace ({} if none)."""
        import json
        r = self._conn.execute(
            "SELECT data FROM user_settings WHERE username=? AND namespace=?",
            (username, namespace)).fetchone()
        if r is None:
            return {}
        try:
            return json.loads(r["data"]) or {}
        except Exception:  # noqa: BLE001 — corrupt blob -> behave as empty
            return {}

    def set_user_settings(self, username: str, namespace: str, data: dict) -> None:
        import json
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO user_settings(username, namespace, data, updated_at) "
                "VALUES (?,?,?,?)",
                (username, namespace, json.dumps(data),
                 datetime.now(timezone.utc).isoformat()))
            self._conn.commit()

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

    def close(self) -> None:
        self._conn.close()
