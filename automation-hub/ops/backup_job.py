"""Backup job: snapshot, verify, ship offsite.

Run by the Kubernetes CronJob in deploy/k8s/base/backup-cronjob.yaml, and
usable by hand for an ad-hoc backup before a risky change:

    python ops/backup_job.py

Three steps, and the middle one is the one most backup systems skip:

1. **Snapshot.** Reuses ``services.backup.backup_now``, which copies every
   SQLite database through the sqlite3 backup API — consistent even if the
   engine is writing mid-copy — and every JSON store beside it.

2. **Verify.** Opens each database in the fresh snapshot and queries it. An
   unverified backup is a hypothesis: the failure mode that actually hurts is
   discovering at restore time that months of nightly jobs were faithfully
   copying a corrupt file. This turns that into an alert tonight.

3. **Ship offsite.** A backup on the same PersistentVolume as the data protects
   against "I deleted the wrong row". It does not protect against losing the
   volume, the cluster or the region, which are the events that end companies.
   Set HUB_BACKUP_S3_BUCKET to copy the snapshot out.

Exit codes: 0 success, 1 failure. The CronJob surfaces a non-zero exit as a
failed Job, and hub_backup_last_success_timestamp_seconds stops advancing,
which is what the HubBackupStale alert watches.
"""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops.log import configure_logging, get_logger  # noqa: E402

configure_logging()
log = get_logger("backup")


def _upload(archive: Path, key: str) -> bool:
    """Copy the archive to S3-compatible storage. Returns True when shipped."""
    bucket = os.environ.get("HUB_BACKUP_S3_BUCKET", "").strip()
    if not bucket:
        log.warning(
            "offsite backup NOT configured — the snapshot exists only on the "
            "same volume as the data it protects, so it survives an accidental "
            "delete but not the loss of the volume. Set HUB_BACKUP_S3_BUCKET.")
        return False

    try:
        import boto3  # noqa: PLC0415 — optional, only needed when offsite is on
    except ImportError:
        # A hard failure on purpose. Asking for offsite backups and silently not
        # getting them is worse than not asking: it produces false confidence
        # that survives right up until the restore.
        log.error("HUB_BACKUP_S3_BUCKET is set but boto3 is not installed — "
                  "offsite backup cannot run. Install boto3 in the image.")
        return False

    endpoint = os.environ.get("HUB_BACKUP_S3_ENDPOINT", "").strip() or None
    client = boto3.client("s3", endpoint_url=endpoint)
    client.upload_file(str(archive), bucket, key)
    log.info("snapshot uploaded", extra={"bucket": bucket, "key": key,
                                         "bytes": archive.stat().st_size})
    return True


def main() -> int:
    data_dir = os.environ.get("HUB_DATA_DIR", "/data")
    log.info("backup starting", extra={"data_dir": data_dir})

    from services.backup import backup_now, restore_check

    result = backup_now(data_dir)
    if not result.get("ok"):
        log.error("snapshot failed", extra={"result": result})
        return 1
    snapshot = result["snapshot"]
    log.info("snapshot written", extra={"snapshot": snapshot,
                                        "files": len(result.get("files", []))})

    check = restore_check(data_dir, snapshot)
    if not check.get("ok", False):
        log.error("snapshot is NOT restorable — treat this as a failed backup",
                  extra={"snapshot": snapshot, "check": check})
        return 1
    log.info("snapshot verified restorable", extra={"snapshot": snapshot})

    src = Path(data_dir) / "backups" / snapshot
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / f"{snapshot}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(src, arcname=snapshot)
        prefix = os.environ.get("HUB_BACKUP_S3_PREFIX", "tradexa-hub").strip("/")
        try:
            _upload(archive, f"{prefix}/{snapshot}.tar.gz")
        except Exception:  # noqa: BLE001
            # The local snapshot is written and verified at this point, so the
            # run has real value even if shipping failed. Fail the Job anyway —
            # a silently un-shipped backup is exactly the false confidence this
            # script exists to prevent.
            log.exception("offsite upload failed")
            return 1

    log.info("backup complete", extra={"snapshot": snapshot,
                                       "pruned": result.get("pruned", [])})
    return 0


if __name__ == "__main__":
    sys.exit(main())
