# Disaster Recovery

What is backed up, how to get it back, and how long that takes.

## Targets

| | Target | Basis |
|---|---|---|
| **RPO** (data you can lose) | **24 hours** | Backups run nightly at 02:17 UTC. With `SUPABASE_URL` configured the ledger and settings mirror continuously, cutting effective RPO for trade history to near zero. |
| **RTO** (time to restore) | **30 minutes** | Restoring a snapshot onto a fresh volume, verified. Dominated by image pull and warm-up, not by the copy. |

These are targets, not guarantees, and they are only real if the drill below is
actually run. An untested restore is a hypothesis.

## What is at risk

| State | Where it lives | Survives pod loss | Survives volume loss |
|---|---|---|---|
| Trade ledger | `ledger.db` on the PVC | yes | only via backup, or Supabase if configured |
| Decision journal, skipped trades | `journal.db`, `skipped.db` | yes | only via backup |
| Paper account, positions | `account.db` | yes | only via backup |
| User accounts, bots | `hub.db` | yes | only via backup |
| Learned lessons, strategy versions | JSON stores | yes | only via backup |
| Market data cache | `market_data.db` | yes | rebuilt automatically — do not restore |
| Sessions | signed cookies, no server state | yes | yes |

The last row is why a full restore does not log everyone out: sessions are
signed with `HUB_SECRET`, not stored.

## What runs

**Nightly, in-process.** The app's daily tasks snapshot every database through
the SQLite backup API — consistent even mid-write — into
`$HUB_DATA_DIR/backups/<UTC timestamp>/`, keeping the newest 7.

**Nightly, as a CronJob** (`deploy/k8s/base/backup-cronjob.yaml`, 02:17 UTC).
Does the two things the in-process job cannot:

1. **Verifies** the snapshot is restorable — opens and queries every database.
2. **Ships it offsite**, if `HUB_BACKUP_S3_BUCKET` is set.

A backup on the same volume as its source protects against a bad `DELETE` and
nothing else. Configure offsite storage or accept that a volume loss is a total
loss:

```bash
kubectl -n tradexa set env cronjob/tradexa-hub-backup \
  HUB_BACKUP_S3_BUCKET=my-backup-bucket \
  HUB_BACKUP_S3_PREFIX=tradexa-hub
```

> `boto3` is not in the image by default. If `HUB_BACKUP_S3_BUCKET` is set and
> `boto3` is missing, the job **fails loudly** rather than skipping the upload —
> silently not shipping backups you asked for is worse than not asking.

## <a id="backup-failing"></a>Alert: backups are stale or have never run

`HubBackupStale` / `HubBackupNeverRan`

```bash
kubectl -n tradexa get cronjob tradexa-hub-backup
kubectl -n tradexa get jobs -l app.kubernetes.io/component=backup
kubectl -n tradexa logs job/<most-recent> | jq -r '"\(.level) \(.message)"'

# Run one now.
kubectl -n tradexa create job --from=cronjob/tradexa-hub-backup manual-$(date +%s)
```

Common causes: the volume is full (`kubectl exec -- df -h /data`); S3
credentials are missing or wrong; a previous job is stuck and
`concurrencyPolicy: Forbid` is blocking every subsequent run — delete the stuck
job.

## Restoring

`automation-hub/ops/restore.py` handles the whole path. It refuses to run while
the engine still holds its lease, keeps a copy of the current state before
overwriting anything, and verifies the result.

```bash
POD=$(kubectl -n tradexa get pod -l app.kubernetes.io/component=engine -o name | head -1)

# 1. What is available?
kubectl -n tradexa exec $POD -- python /app/automation-hub/ops/restore.py --list

# 2. Confirm the one you want is actually restorable.
kubectl -n tradexa exec $POD -- python /app/automation-hub/ops/restore.py \
  --verify 20260731T021700Z

# 3. STOP THE ENGINE. Copying databases out from under an active writer
#    produces a corrupt result. The script refuses to proceed without this.
kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=0
kubectl -n tradexa wait --for=delete pod -l app.kubernetes.io/component=engine --timeout=2m

# 4. Restore. Runs from a web pod, which mounts the same volume.
kubectl -n tradexa exec deploy/tradexa-hub-web -- \
  python /app/automation-hub/ops/restore.py --restore 20260731T021700Z --yes

# 5. Bring it back.
kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=1
kubectl -n tradexa rollout status statefulset/tradexa-hub-engine
```

The previous state is kept at `backups/pre-restore-<timestamp>/`. If you
restored the wrong snapshot, that directory is how you undo it.

## Scenarios

### A pod dies

Nothing to do. Kubernetes reschedules it; the PVC reattaches. If it was the
engine, a standby (or the replacement) takes the lease within
`HUB_LEASE_TTL_S`. **RTO: under 2 minutes, automatic.**

### The node dies

The PVC must reattach on a new node. With ReadWriteMany this is automatic; with
ReadWriteOnce the volume may take several minutes to detach first. Watch
`kubectl -n tradexa describe pod` for `FailedAttachVolume`. **RTO: 2–10 minutes.**

### The volume is lost

The real disaster, and the one offsite backups exist for.

```bash
# 1. Recreate the claim (delete the old one first if it still exists).
kubectl -n tradexa apply -f deploy/k8s/base/pvc.yaml

# 2. Start a web pod so something mounts it; keep the engine at zero.
kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=0
kubectl -n tradexa scale deploy/tradexa-hub-web --replicas=1

# 3. Pull the newest archive from object storage into the volume.
kubectl -n tradexa exec deploy/tradexa-hub-web -- sh -c \
  'aws s3 cp s3://$HUB_BACKUP_S3_BUCKET/tradexa-hub/ /data/backups/ --recursive --exclude "*" --include "*.tar.gz" && \
   cd /data/backups && for f in *.tar.gz; do tar xzf "$f"; done'

# 4. Restore, then bring everything back.
kubectl -n tradexa exec deploy/tradexa-hub-web -- \
  python /app/automation-hub/ops/restore.py --list
kubectl -n tradexa exec deploy/tradexa-hub-web -- \
  python /app/automation-hub/ops/restore.py --restore <snapshot> --yes
kubectl -n tradexa scale statefulset/tradexa-hub-engine --replicas=1
```

**RTO: ~30 minutes. RPO: up to 24 hours** — reconcile against the exchange for
anything that happened after the snapshot.

### The cluster or region is lost

```bash
kubectl apply -k deploy/k8s/overlays/production   # against the new cluster
```

Then follow "the volume is lost". Everything needed to rebuild is in this
repository plus the object store; nothing is configured only by hand. The two
things that are *not* in git are the Secret and DNS — keep the secret material
in your secrets manager (see `deploy/k8s/base/externalsecret.yaml`) and the DNS
records somewhere you can reach without this cluster.

**RTO: 1–2 hours,** dominated by cluster provisioning.

### The database is corrupt but the volume is fine

Readiness fails on `database`, or the engine crash-loops with SQLite errors.

```bash
kubectl -n tradexa exec deploy/tradexa-hub-web -- \
  sh -c 'for f in /data/*.db; do echo "== $f"; python -c "
import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute(\"PRAGMA integrity_check\").fetchone()[0])" "$f"; done'
```

Anything other than `ok` means restore that snapshot. Do not attempt in-place
repair on trading data — a partially repaired ledger is worse than a slightly
stale one, because you cannot tell which rows are trustworthy.

## The drill

**Quarterly, on staging.** A restore procedure nobody has executed is not a
procedure.

1. Note the current trade count.
2. Trigger a backup: `kubectl -n tradexa-staging create job --from=cronjob/tradexa-hub-backup drill-$(date +%s)`
3. Destroy state: `kubectl -n tradexa-staging exec deploy/tradexa-hub-web -- sh -c 'rm -f /data/*.db'`
4. Confirm the service notices — readiness should fail on `database`.
5. Restore following the steps above. **Time it.**
6. Confirm the trade count matches step 1.
7. Record the elapsed time. If it exceeds the 30-minute RTO, fix the procedure
   or change the target — a target nobody meets is not a target.

Log each drill (date, who, elapsed, what broke) below.

| Date | Ran by | RTO achieved | Notes |
|---|---|---|---|
| _(pending first drill)_ | | | |
