# Preserve opencode sessions

## Context

Craft sessions use `opencode serve` as the long-lived agent runtime inside a
sandbox. Onyx persists the `BuildSession.opencode_session_id` in Postgres so a
later turn can reconnect to the same opencode session instead of creating a
fresh one every message.

That ID alone is not enough after a Kubernetes sandbox sleeps, is evicted, or is
recreated. The opencode session rows live inside opencode's data directory in
the sandbox filesystem. If the sandbox-level opencode data is not persisted and
restored, the Postgres ID points at nothing.

The current implementation persists opencode history as sandbox-global state,
separate from normal per-session workspace snapshots.

## Goals

1. Preserve opencode's session history across Kubernetes sandbox sleep,
   recovery, and reprovision.
2. Keep durable storage ownership in the API server / FileStore layer, not in
   sandbox pods.
3. Keep normal session snapshots focused on per-session files.
4. Keep Docker workspace snapshots from carrying opencode data; opencode
   history persistence is currently a Kubernetes-only capability.
5. Be optimistic when a saved opencode ID is missing from a restored DB: mint a
   replacement ID and persist it. A later follow-up can replay saved chat history
   into that replacement session.
6. Treat opencode's session store as implementation data. Deleting an Onyx
   BuildSession removes the product-visible record and best-effort deletes the
   live opencode session when the sandbox is running; failure does not block
   Onyx deletion and does not prune durable history archives.

## Storage Model

There are two distinct persistence surfaces.

### Per-session workspace snapshots

Normal session snapshots capture only session-local user output:

- `outputs/`
- `attachments/` when present and non-empty

They deliberately do not capture `.opencode-data`. These archives are created
and restored by the sandbox sidecar through:

- `POST /snapshot/create`
- `POST /snapshot/restore/{session_id}`

The sidecar owns local filesystem access. The API server streams the archive
into FileStore through `SnapshotManager`.

### Sandbox-global opencode history

Opencode history is shared by all BuildSessions in a sandbox. In Kubernetes the
pod is configured with:

- `OPENCODE_DATA_HOME=/workspace/opencode-data`

The opencode data root is:

```text
/workspace/opencode-data
```

The durable FileStore object is deterministic per sandbox:

```text
sandbox-snapshots/{tenant_id}/{sandbox_id}/opencode-history.tar.gz
```

The archive stores that directory under a stable archive root:

```text
.opencode-data/
```

This keeps opencode persistence separate from session workspaces while avoiding
a custom per-session opencode store that would not match opencode's actual
sandbox-level data model.

## Important Components

### `SnapshotManager`

`backend/onyx/server/features/build/sandbox/snapshot_manager.py`

Owns FileStore persistence for both normal session snapshots and sandbox-global
opencode history snapshots. Normal sidecar-created workspace snapshots keep the
sidecar's archive and uncompressed-size checks. Opencode history snapshots use
the deterministic storage path above and are not capped by workspace snapshot
limits. Kubernetes still bounds the pod-local opencode data volume with an
`emptyDir.sizeLimit`.

### Sandbox sidecar snapshot endpoints

`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/server.py`

The sidecar exposes local filesystem operations as signed HTTP endpoints. It
does not upload to S3 and does not know tenant storage credentials.

For opencode history:

- `GET /ready` returns healthy only after the startup restore path has restored
  or explicitly skipped opencode history. This endpoint is used as the
  restartable init sidecar startup gate, not as the steady-state pod readiness
  signal.
- `POST /opencode-history/create` returns `204` when the opencode data directory
  has no content, otherwise streams a gzip archive.
- `POST /opencode-history/restore` accepts a signed, hash-verified archive body
  and restores the opencode data directory locally.
- `POST /opencode-history/mark-restored` marks a fresh sandbox ready when no
  durable history snapshot exists.

### Opencode history archive helpers

`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/opencode_history.py`

This module owns the opencode data archive logic:

- keep the opencode data path outside `/workspace/sessions`
- stage the opencode data directory before archiving it
- replace the staged `opencode/opencode.db`, when present, with a SQLite
  backup so the archive carries a coherent DB snapshot even if `opencode serve`
  is running
- restore the archive with Python's standard tar `data` filter, then replace
  `/workspace/opencode-data` with the extracted `.opencode-data/` root
- ignore unrelated top-level archive entries outside `.opencode-data/`
- if the known current `opencode/opencode.db` is present but corrupt after
  restore, clear the restored opencode data directory so `opencode serve` starts
  fresh
- rely on signed sidecar endpoints and SHA-256 request verification for transport
  integrity
- write the startup restore marker under sidecar-owned managed state at
  `/workspace/managed/.onyx/opencode-history-restored`

This is separate from `snapshot.py`, which now remains focused on normal
session workspace snapshotting.

### Kubernetes sandbox manager

`backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py`

The K8s manager coordinates pod lifecycle, sidecar calls, FileStore streaming,
and startup restore gating.

It is the only backend currently advertising:

```python
supports_opencode_history_persistence = True
```

Craft's Kubernetes pod template uses a native restartable init sidecar, so Craft
Helm deployments require Kubernetes 1.33 or newer. This is enforced at
deployment/render time by the chart, not by a runtime backend version check.

## Provision And Restore Flow

When a Kubernetes sandbox pod starts:

1. Kubernetes starts the firewall init container.
2. Kubernetes starts the restartable `sidecar` init container. Its health
   endpoint is available, but its startup endpoint stays blocked.
3. The K8s manager ensures the sandbox Service exists and publishes not-ready
   pod addresses so the sidecar can be reached before pod readiness.
4. If no durable opencode history snapshot exists, the manager posts a signed
   request to `/opencode-history/mark-restored`.
5. If a durable history snapshot exists, the API server reads it from FileStore
   into a temp file, computes its SHA-256, and posts it to
   `/opencode-history/restore`.
6. The sidecar restores the opencode data directory. If the restored current
   opencode DB is corrupt, the sidecar clears that data so opencode can start
   fresh instead of starting against known-bad state.
7. The sidecar marks opencode history restored.
8. The sidecar `/ready` endpoint succeeds, which releases the restartable init
   sidecar startup gate.
9. Kubernetes starts the `sandbox` app container. Its entrypoint runs
   `opencode serve` with `XDG_DATA_HOME` pointed at
   `/workspace/opencode-data`.
10. The K8s manager waits for pod readiness and `opencode serve` readiness.

The important property is that `opencode serve` never starts before restore
has completed or been explicitly skipped.

When the K8s manager finds an already healthy sandbox pod, it reuses that pod
without re-running startup history restore.

## Snapshot Creation Flow

Opencode history snapshots are created before a sandbox sleeps and during
best-effort recovery.

1. The K8s manager signs a request to `/opencode-history/create`.
2. The sidecar checks whether the opencode data directory has content.
3. If it has no content, the sidecar returns `204`.
4. If it has content, the sidecar stages the opencode data directory, replaces
   the staged SQLite DB with a `sqlite3.Connection.backup()` copy, creates a
   tar.gz archive, and streams it back.
5. The API server streams the response into `SnapshotManager`.
6. `SnapshotManager` stores it at the stable sandbox-level FileStore key.

If the sidecar returns `204` for an empty live store, the manager preserves any
existing durable history archive. That is important for idle/recovery paths: a
transient live empty/missing DB should not destroy the last known good history.

## Send Message Flow

The prompt path is intentionally optimistic.

1. The session row carries `BuildSession.opencode_session_id` when one has been
   persisted.
2. Before a turn, `_ensure_opencode_session_id` mints and persists an opencode
   session ID if the row has none.
3. `yield_sandbox_events` calls `sandbox_manager.send_message` with the saved
   ID and an `on_opencode_session_resolved` callback.
4. `_send_message_via_serve` calls `OpencodeServeClient.ensure_session`.
5. If the saved ID exists, opencode returns `200` and the same ID is reused.
6. If opencode returns `404`, Onyx creates a fresh opencode session and invokes
   the callback so the BuildSession row is updated.
7. Non-404 lookup errors still raise. A runtime outage should not silently mint
   a replacement session.
8. The message is sent to the resolved opencode session and normal event
   streaming proceeds.

This means a restored sandbox with a missing opencode ID does not fail the user
turn. It starts a new opencode session and records the new ID. The tradeoff is
that opencode itself does not yet receive prior chat history in that newly
created session. That replay behavior is intentionally out of scope for this
change.

## Delete Session Flow

Deleting a BuildSession deletes Onyx's durable session record. When the sandbox
is running and the row has an `opencode_session_id`, Onyx also makes a
best-effort request to delete that live opencode session. That cleanup is an
optimization only: failures are logged and do not block deleting the Onyx row.

Opencode history remains sandbox-global implementation data, so session delete
does not prune durable opencode history archives. If opencode still has a row
for the deleted BuildSession, that row is orphaned and no longer reachable
through Onyx.

1. `SessionManager.delete_session` acquires the session prompt slot.
2. If the sandbox is running and the BuildSession has an opencode session ID,
   the manager best-effort deletes that live opencode session.
3. Normal workspace cleanup and Snapshot FileStore cleanup proceed.
4. The BuildSession DB row is deleted.

For a sleeping or otherwise not-running sandbox, deletion does not try to edit
or validate opencode history. The Onyx row is removed, so any stale opencode
record left in a durable history archive is orphaned implementation data.

## Idle Sleep Flow

The sandbox cleanup task handles idle running sandboxes.

1. If the backend supports opencode history persistence, it first attempts an
   opencode history snapshot.
2. If that snapshot fails but the sandbox still passes health check, the task
   leaves the sandbox running. Sleeping a healthy sandbox without fresh history
   would risk losing recent agent context.
3. If the pod is already unreachable, the task logs a warning and continues
   cleanup. At that point the live filesystem cannot be trusted or accessed for
   a fresh snapshot.
4. The task then snapshots each session workspace.
5. The sandbox can be put to sleep after required snapshots complete.

## Recovery Flow

When Onyx detects an unhealthy running sandbox and needs to terminate/recover it,
the lifecycle code attempts a best-effort opencode history snapshot before
termination.

This path is best-effort because the sandbox may already be partially dead. A
failure is logged but does not block recovery forever.

On reprovision, the normal restore flow restores the last durable opencode
history snapshot if one exists.

## Reset / Start Fresh Flow

User-requested sandbox reset is a destructive "start fresh" operation.

1. Delete the durable opencode history snapshot.
2. Terminate the sandbox resources.
3. Mark the sandbox DB row as `TERMINATED` in the caller-owned transaction.
4. Commit only after the durable history delete and sandbox termination succeed.

The durable FileStore delete is external to the DB transaction. If termination
fails after history deletion succeeds, the API reports reset failure and rolls
back DB state, but the durable history object is already gone. This preserves
the "start fresh" invariant on the next successful provision.

If the sandbox row is already `TERMINATED`, reset has no live pod or DB status
transition left to protect. In that case the durable history delete is
best-effort: failures are logged and the reset still returns success. A later
reset can retry the delete once FileStore recovers.

This is intentionally different from idle sleep. Sleep preserves history; reset
removes it.

## Why This Is Not A Normal Session Snapshot

The normal snapshot loop iterates session directories and stores each session's
workspace. That is the right model for outputs and attachments.

Opencode history is different:

- opencode stores all sessions in one sandbox-level data store
- a per-session archive cannot safely represent the shared data store
- multiple BuildSessions can share the same opencode history store
- deleting one session can leave orphaned opencode rows because Onyx does not
  edit opencode's internal store on BuildSession deletion
- reset must delete the shared archive, not merge or preserve per-session stores

So the implementation reuses the same high-level snapshot infrastructure
(`SnapshotManager`, FileStore, signed sidecar streaming), but keeps opencode
history as a sandbox-level archive with its own create/restore endpoints and
policy.

## Operational Invariants

- The sandbox pod does not own durable storage credentials.
- The API server owns FileStore reads/writes.
- The sidecar owns pod-local filesystem reads/writes.
- Normal session snapshots do not contain `.opencode-data`.
- Opencode history is stored on a sandbox-global volume outside the
  `/workspace/sessions` tree.
- Opencode history snapshots contain the full `.opencode-data/` archive root.
- A corrupt restored `opencode/opencode.db` is discarded in favor of a fresh
  opencode data directory.
- `opencode serve` starts only after startup history restore is complete.
- Craft Helm deployment fails fast on Kubernetes versions older than 1.33, before
  the backend starts provisioning sandbox pods.
- A missing saved opencode ID during send mints a new session and persists it.
- Runtime lookup errors other than `404` still fail the turn.
- Craft Helm deployment fails fast if `ENABLE_CRAFT=true` is paired with a
  non-Kubernetes sandbox backend.
- Session delete best-effort removes a live opencode session when possible, but
  still removes the BuildSession row if that cleanup fails.
- Session delete does not mutate durable opencode history archives.
- Reset deletes durable opencode history before terminating the sandbox so a
  failed delete does not leave a terminated sandbox with restorable stale
  history.

## Known Follow-Up

If a restored sandbox does not contain the saved opencode ID, Onyx now mints a
new opencode session and persists it. That avoids blocking the user, but the
new opencode session does not yet contain prior chat history.

The planned follow-up is to detect this replacement-session case and replay the
saved BuildMessage history into opencode before sending the next user prompt.
That should live above the low-level snapshot/restore path. The snapshot layer
should continue to restore the DB when possible and stay storage-focused.

## Files Worth Reading

- `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/opencode_history.py`
- `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/server.py`
- `backend/onyx/server/features/build/sandbox/snapshot_manager.py`
- `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py`
- `backend/onyx/server/features/build/sandbox/opencode/serve_client.py`
- `backend/onyx/server/features/build/sandbox/serve_transport.py`
- `backend/onyx/server/features/build/session/streaming.py`
- `backend/onyx/server/features/build/session/manager.py`
