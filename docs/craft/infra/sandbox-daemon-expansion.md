# Sandbox Daemon Expansion Notes

The sandbox daemon is the signed HTTP control plane running in the sandbox
sidecar. It owns pod-local filesystem operations only.

Current daemon responsibilities:

- `GET /health`
- `POST /push?mount_path=...`
- `POST /snapshot/create`
- `POST /snapshot/restore/{session_id}`

Snapshot endpoints intentionally do not accept bucket names or storage paths.
Durable storage is API-server-owned FileStore IO.

## Snapshot create

Request body:

```json
{"session_id": "<uuid>"}
```

Response:

- `204` when there is no snapshot content.
- `200 application/gzip` streaming a tarball of `outputs/` and `attachments/`.
  Opencode history is sandbox-global and uses separate opencode-history
  endpoints.

## Snapshot restore

Path:

```text
POST /snapshot/restore/{session_id}
```

Headers:

- `X-Push-Signature`
- `X-Push-Timestamp`
- `X-Bundle-Sha256`

Body: `application/gzip` archive bytes.

The daemon verifies the signature and checksum, writes the archive to a
temporary file, extracts it into `/workspace/sessions/{session_id}`, and
bootstraps dependencies if the restored web app has a `bun.lock`.

Higher-level session setup remains in `KubernetesSandboxManager`, which
regenerates AGENTS/config files and starts Next.js after restore.
