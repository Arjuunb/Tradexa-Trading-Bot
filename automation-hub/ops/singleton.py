"""A lease that keeps exactly one trading engine running.

The engine, the watchdog, the monitor agent and the daily-report scheduler are
singletons. Two of them against one account is not a degraded service, it is
duplicate order flow, doubled risk exposure and two conflicting views of the
same position. So the deployment guarantees at-most-one three ways over:

1. ``HUB_ROLE`` (ops/runtime.py) — web replicas never start workers at all.
2. A StatefulSet of one for the engine. Unlike a Deployment, which may briefly
   run old and new pods together during a rollout, a StatefulSet terminates the
   old pod before creating its replacement.
3. This lease, which is the backstop for when 1 and 2 are misconfigured — the
   failure mode a human actually produces, by scaling something "just to see".

A process that cannot take the lease does not exit. It stays up as a warm
standby, polling. If the leader dies its lease expires and a standby promotes
itself within ``ttl_s``, which is what turns a singleton into something that
survives node loss rather than merely refusing to double-run.

**Scope, stated plainly:** the lease is stored in SQLite and therefore only
coordinates processes that share that file. That is exactly the case it is
built for — the engine's PersistentVolume — and it is a real guarantee there.
It is *not* a distributed lock: two engines with two separate volumes will each
happily take "the" lease. Cross-node mutual exclusion comes from the StatefulSet,
with this as defence in depth. Point ``HUB_LEASE_DB`` at shared storage, or move
the table to Postgres, and it becomes a true distributed lease.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from ops import runtime

_log = logging.getLogger("hub.singleton")

DEFAULT_TTL_S = 60.0


class Lease:
    """A time-bounded, renewable claim on a named singleton role."""

    def __init__(self, db_path: str, name: str = "auto-engine", *,
                 ttl_s: float = DEFAULT_TTL_S, owner: str | None = None) -> None:
        self.db_path = str(db_path)
        self.name = name
        self.ttl_s = float(ttl_s)
        self.owner = owner or runtime.instance_id()
        self._held = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ensure_schema()

    # ------------------------------------------------------------- storage
    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None hands transaction control to us so the
        # read-modify-write in acquire() can run inside one BEGIN IMMEDIATE.
        conn = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _ensure_schema(self) -> None:
        try:
            with closing(self._connect()) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ops_lease (
                        name        TEXT PRIMARY KEY,
                        owner       TEXT NOT NULL,
                        expires_at  REAL NOT NULL,
                        acquired_at REAL NOT NULL
                    )
                """)
        except sqlite3.Error:
            _log.warning("lease table unavailable at %s", self.db_path, exc_info=True)

    # ------------------------------------------------------------ lifecycle
    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        """Take the lease if it is free, expired, or already ours.

        The conditional upsert is the whole mechanism. ``WHERE expires_at < now
        OR owner = me`` means a live lease held by someone else is left alone,
        and the write is atomic under BEGIN IMMEDIATE, so two processes racing
        cannot both come away believing they won.
        """
        now = time.time()
        try:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""
                    INSERT INTO ops_lease (name, owner, expires_at, acquired_at)
                    VALUES (:name, :owner, :expires, :now)
                    ON CONFLICT(name) DO UPDATE SET
                        owner       = excluded.owner,
                        expires_at  = excluded.expires_at,
                        acquired_at = CASE WHEN ops_lease.owner = excluded.owner
                                           THEN ops_lease.acquired_at
                                           ELSE excluded.acquired_at END
                    WHERE ops_lease.expires_at < :now OR ops_lease.owner = :owner
                """, {"name": self.name, "owner": self.owner,
                      "expires": now + self.ttl_s, "now": now})
                # Read back rather than trusting rowcount: the DO UPDATE ... WHERE
                # simply does nothing when another process holds a live lease,
                # which is a no-op, not an error.
                row = conn.execute(
                    "SELECT owner FROM ops_lease WHERE name = ?", (self.name,)
                ).fetchone()
                conn.execute("COMMIT")
        except sqlite3.Error:
            _log.warning("lease acquire failed for %s", self.name, exc_info=True)
            self._set_held(False)
            return False

        won = bool(row) and row[0] == self.owner
        if won and not self._held:
            _log.info("acquired singleton lease", extra={"lease": self.name, "owner": self.owner})
        self._set_held(won)
        return won

    def renew(self) -> bool:
        """Extend our claim. Fails if we lost it — which happens when a pause
        longer than the TTL (a long GC, a suspended node) let a standby take
        over. The caller must then stop working immediately."""
        now = time.time()
        try:
            with closing(self._connect()) as conn:
                cur = conn.execute(
                    "UPDATE ops_lease SET expires_at = ? WHERE name = ? AND owner = ?",
                    (now + self.ttl_s, self.name, self.owner))
                ok = cur.rowcount > 0
        except sqlite3.Error:
            _log.warning("lease renew failed for %s", self.name, exc_info=True)
            return False
        if not ok and self._held:
            _log.error("LOST singleton lease — another process has taken over",
                       extra={"lease": self.name, "owner": self.owner})
        self._set_held(ok)
        return ok

    def release(self) -> None:
        """Give the lease up on a clean shutdown so a standby promotes in
        seconds instead of waiting out the full TTL."""
        try:
            with closing(self._connect()) as conn:
                conn.execute("DELETE FROM ops_lease WHERE name = ? AND owner = ?",
                             (self.name, self.owner))
            _log.info("released singleton lease", extra={"lease": self.name})
        except sqlite3.Error:
            _log.debug("lease release failed", exc_info=True)
        self._set_held(False)

    def holder(self) -> dict | None:
        """Who holds it and for how long — surfaced on /health/ready so an
        operator can see which pod is the leader without reading logs."""
        try:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT owner, expires_at, acquired_at FROM ops_lease WHERE name = ?",
                    (self.name,)).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return None
        return {"owner": row[0], "expires_in_s": round(row[1] - time.time(), 1),
                "held_for_s": round(time.time() - row[2], 1), "is_self": row[0] == self.owner}

    def _set_held(self, value: bool) -> None:
        self._held = value
        try:
            from ops import metrics

            metrics.set_engine_leader(value)
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------- supervision
    def supervise(self, on_acquire, on_lose) -> None:
        """Run the elect/renew loop in a daemon thread.

        ``on_acquire`` starts the singleton work, ``on_lose`` stops it. Both are
        called from this thread and must be safe to call more than once — a
        flapping lease should not depend on the callbacks being perfectly
        balanced.
        """
        if self._thread is not None:
            return

        # Renew at a third of the TTL: two consecutive renewals can fail (a
        # transient lock, a slow disk) before the lease actually expires.
        interval = max(1.0, self.ttl_s / 3.0)

        def _loop() -> None:
            was_leader = False
            while not self._stop.is_set():
                try:
                    leader = self.renew() if was_leader else self.acquire()
                    if leader and not was_leader:
                        on_acquire()
                    elif not leader and was_leader:
                        _log.error("stepping down — singleton work stopping")
                        on_lose()
                    elif not leader and not was_leader:
                        h = self.holder()
                        _log.debug("standby; lease held elsewhere", extra={"holder": h})
                    was_leader = leader
                except Exception:  # noqa: BLE001
                    _log.exception("lease supervision cycle failed")
                self._stop.wait(interval)

        with self._lock:
            self._thread = threading.Thread(target=_loop, name="lease-supervisor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5)
        self.release()
