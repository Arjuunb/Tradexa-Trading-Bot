"""Restore the hub's state from a snapshot.

The deliberately unglamorous other half of the backup story. Backups get built
and monitored; restores get discovered at 3am during the worst hour of the
year. This exists so the restore is a documented command someone has run
before, not an improvisation.

    python ops/restore.py --list
    python ops/restore.py --verify 20260731T021700Z
    python ops/restore.py --restore 20260731T021700Z --yes

Three safety properties, each there because of how restores actually go wrong:

**It refuses to run while the engine is live.** Copying a database out from
under an active writer produces a corrupt file and a confusing aftermath.
Scale the engine to zero first; the script says so rather than assuming.

**It snapshots the current state before overwriting it.** The classic
second disaster is restoring the wrong snapshot and destroying the evidence
needed to work out what actually happened. The pre-restore copy is written to
``backups/pre-restore-<timestamp>``.

**It verifies before and after.** Every database is opened and queried both in
the snapshot and in the restored directory, so "the restore worked" is a
checked claim rather than an absence of error messages.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops.log import configure_logging, get_logger  # noqa: E402

configure_logging()
log = get_logger("restore")


def _data_dir() -> Path:
    return Path(os.environ.get("HUB_DATA_DIR", "/data"))


def cmd_list() -> int:
    from services.backup import list_backups

    backups = list_backups(str(_data_dir())).get("backups", [])
    if not backups:
        print(f"no snapshots found under {_data_dir() / 'backups'}")
        return 1
    print(f"{'SNAPSHOT':<24} {'FILES':>6} {'SIZE':>12}")
    for b in backups:
        print(f"{b['snapshot']:<24} {b['files']:>6} {b['bytes'] / 1_048_576:>9.1f} MB")
    return 0


def cmd_verify(snapshot: str) -> int:
    from services.backup import restore_check

    result = restore_check(str(_data_dir()), snapshot)
    for name, info in result.get("databases", {}).items():
        state = "ok" if info["ok"] else f"FAILED: {info.get('error')}"
        tables = info.get("tables", "-")
        print(f"  {name:<28} {state:<40} tables={tables}")
    if result.get("ok"):
        print(f"\n{snapshot} is restorable")
        return 0
    print(f"\n{snapshot} is NOT restorable: {result.get('error', 'one or more databases failed')}",
          file=sys.stderr)
    return 1


def _engine_looks_live(data_dir: Path) -> bool:
    """True when something still holds the singleton engine lease.

    Best effort, and it says so: the lease only reflects processes sharing this
    data directory. It catches the common mistake — restoring onto a volume a
    running engine is still writing to — and cannot catch every arrangement.
    """
    lease_db = os.environ.get("HUB_LEASE_DB") or str(data_dir / "ops_lease.db")
    if not Path(lease_db).exists():
        return False
    try:
        from ops.singleton import Lease

        holder = Lease(lease_db, "auto-engine", owner="restore-probe").holder()
    except Exception:  # noqa: BLE001
        return False
    return bool(holder) and holder.get("expires_in_s", -1) > 0


def cmd_restore(snapshot: str, *, confirmed: bool, force: bool) -> int:
    data_dir = _data_dir()
    src = data_dir / "backups" / snapshot
    if not src.is_dir():
        log.error("snapshot not found", extra={"snapshot": snapshot, "path": str(src)})
        return 1

    if cmd_verify(snapshot) != 0:
        log.error("refusing to restore an unverified snapshot")
        return 1

    if _engine_looks_live(data_dir) and not force:
        log.error(
            "the engine still holds its lease — restoring now would copy over "
            "files it is actively writing. Scale it down first:\n"
            "    kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=0\n"
            "Then re-run. Use --force only if you are certain nothing is writing.")
        return 1

    if not confirmed:
        print(f"\nThis will OVERWRITE the live state in {data_dir} with {snapshot}.")
        print("Re-run with --yes to proceed.")
        return 1

    # Safety copy first. Restoring the wrong snapshot is a routine mistake, and
    # without this it is an unrecoverable one.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safety = data_dir / "backups" / f"pre-restore-{stamp}"
    safety.mkdir(parents=True, exist_ok=True)
    kept = 0
    for f in data_dir.iterdir():
        if f.is_file() and f.suffix in (".db", ".json"):
            shutil.copy2(f, safety / f.name)
            kept += 1
    log.info("current state preserved", extra={"path": str(safety), "files": kept})

    restored = []
    for f in sorted(src.iterdir()):
        if f.is_file() and f.name != "manifest.json":
            shutil.copy2(f, data_dir / f.name)
            restored.append(f.name)
    log.info("files restored", extra={"snapshot": snapshot, "files": restored})

    # Verify the RESTORED directory, not the snapshot: the copy itself can fail
    # on a full disk, and a half-written database passes no query.
    import sqlite3
    bad = []
    for f in sorted(data_dir.glob("*.db")):
        try:
            with sqlite3.connect(str(f)) as conn:
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        except sqlite3.Error as exc:
            bad.append(f"{f.name}: {exc}")
    if bad:
        log.error("restored files did NOT verify", extra={"failures": bad,
                                                          "safety_copy": str(safety)})
        return 1

    log.info("restore complete and verified", extra={
        "snapshot": snapshot, "files": len(restored), "safety_copy": str(safety)})
    print(f"\nRestored {len(restored)} files from {snapshot}.")
    print(f"Previous state kept at {safety}")
    print("Bring the engine back up:")
    print("    kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=1")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore hub state from a backup snapshot.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="list available snapshots")
    group.add_argument("--verify", metavar="SNAPSHOT", help="check a snapshot is restorable")
    group.add_argument("--restore", metavar="SNAPSHOT", help="restore a snapshot")
    ap.add_argument("--yes", action="store_true", help="confirm the overwrite")
    ap.add_argument("--force", action="store_true",
                    help="restore even if the engine lease still looks held")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.verify:
        return cmd_verify(args.verify)
    return cmd_restore(args.restore, confirmed=args.yes, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
