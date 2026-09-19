# Snapshot Retention

## What a snapshot is

When a Craft sandbox goes idle, the cleanup task snapshots each session's
workspace (`outputs/`, `attachments/`, `.opencode-data/`) into a `tar.gz` and
persists it through the Onyx FileStore, then terminates the pod. On wake, the
latest snapshot is restored. Snapshots are internal sleep/wake plumbing — they
are not a user-facing version history.

## Retention policy: keep exactly one per session (prune-on-write)

We keep exactly **one snapshot per session — the most recent**. Every snapshot
is superseded by the next one taken for that session, so there is no value in
retaining older ones.

Rather than letting snapshots accumulate and sweeping them with a periodic job,
we **prune on write**: in `cleanup_idle_sandboxes_task`, immediately after a
session's new snapshot is written, `_prune_prior_session_snapshots` deletes that
session's prior snapshots (the ones captured *before* the new one was created).
The new snapshot is fully durable before any old one is removed, so a session is
never left without a restorable snapshot, and storage never accumulates.

This also self-heals: each session's reap prunes *all* of its prior snapshots,
so any backlog (e.g. rows left by a past partial failure) is cleared on that
session's next reap.

### Deletion is blob-then-row, idempotent, best-effort

For each superseded snapshot we delete the file-store blob first, then the
`snapshot` DB row. `SnapshotManager.delete_snapshot` is **idempotent** — a
missing blob counts as already-deleted (`delete_file(error_on_missing=False)`),
so a row whose blob was already removed in a prior partial run still gets its
row dropped. A genuine delete failure (e.g. S3 unreachable) leaves that row in
place to be retried on the session's next reap, so a blob and its row never leak
out of sync.

### Rollout

No periodic task, no beat entry, no config knobs, no DB migration. Restart
Celery workers to pick up the new reap behavior.
