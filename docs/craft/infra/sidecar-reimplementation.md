# Sidecar Reimplementation for Craft Sandboxes

The sandbox pod uses one app container plus one native restartable init
sidecar from the same image:

- `sandbox`: untrusted agent/code execution.
- `sidecar`: signed control-plane filesystem API for bundle pushes and
  snapshot tar/untar operations. It is rendered in `initContainers` with
  `restartPolicy: Always`.

The sidecar is not a durable-storage client. It does not receive S3 bucket
names, AWS credentials, or workload identity. Snapshot bytes are streamed
between the API server and sidecar over the signed sidecar HTTP API; the API
server persists and restores those bytes through the normal Onyx FileStore.

## Current architecture

```text
Pod: sandbox-{id}
ServiceAccount: sandbox
shareProcessNamespace: false

initContainers:
  sandbox-init
    - firewall/proxy bootstrap
    - must complete before user code

  sidecar
    - restartPolicy: Always
    - daemon on :8731
    - POST /push for bundle materialization
    - POST /snapshot/create for gzip snapshot stream
    - POST /snapshot/restore/{session_id} for gzip restore stream
    - read/write /workspace/managed
    - read/write /workspace/sessions
    - no snapshot storage credentials

containers:
  sandbox
    - opencode agent
    - Next.js dev server
    - read-only /workspace/managed
    - read/write /workspace/sessions
    - no snapshot storage credentials
```

## Snapshot flow

Create:

1. API server signs and posts `{"session_id": ...}` to
   `/snapshot/create`.
2. Sidecar validates the signature, tars `outputs/` and `attachments/`, and
   streams `application/gzip` back. Empty workspaces return `204`. Opencode
   history is sandbox-global and uses separate opencode-history endpoints.
3. API server hands the stream to `SnapshotManager.persist_snapshot_from_stream`.
4. `SnapshotManager` stores the archive in `get_default_file_store()` with
   `FileOrigin.SANDBOX_SNAPSHOT`.

Restore:

1. API server reads the snapshot file id through
   `SnapshotManager.restore_snapshot_to_stream`.
2. API server signs and posts the archive bytes to
   `/snapshot/restore/{session_id}` with `X-Bundle-Sha256`.
3. Sidecar validates the signature and checksum, writes the request body to a
   temporary archive, extracts it under `/workspace/sessions/{session_id}`, and
   reinstalls dependencies when needed.
4. API server regenerates session-local config and starts the Next.js dev
   server when a preview port is assigned.

## Deployment contract

- Helm renders `ServiceAccount/sandbox` without storage annotations.
- Helm renders sandbox manager RBAC for the Onyx workload ServiceAccount and
  any `craft.extraBoundServiceAccounts`.
- Kubernetes `>= 1.33` is required for native restartable init sidecar
  containers.
- Terraform does not create Craft-specific snapshot buckets or roles.
- The main FileStore configuration is the only durable storage configuration
  needed for snapshots.

## Tests to keep pinned

- Sidecar unit tests for signed create/restore, checksum validation, and replay
  resistance.
- Pod spec tests proving storage env vars are absent from the sandbox app
  container and sidecar init container.
- K8s external dependency tests proving snapshot create/restore round trips via
  FileStore.
