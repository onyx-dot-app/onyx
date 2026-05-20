# Sandbox Daemon Expansion

Migrate all pod-side operations from `kubectl exec` (via `kubernetes.stream`) to the in-pod HTTP daemon on port 8731. Eliminates shell escaping fragility, WebSocket-per-call overhead, and the overpowered `pods/exec` RBAC permission from api-server's service account.

Companion doc: `sandbox-file-push.md` — describes the existing push primitive this plan builds on.

## Issues to Address

**Shell escaping is a correctness and security risk.** `setup_session_workspace` builds multi-line bash scripts with `printf '%s' '{agent_instructions_escaped}'` where the content has single quotes backslash-escaped. Any template change that introduces unexpected characters can silently corrupt the file or break the script. The same pattern repeats for `opencode.json`, `org_info/`, and the attachments section injection in `_ensure_agents_md_attachments_section`.

**WebSocket setup per call is slow.** Each `k8s_stream` call negotiates a new WebSocket connection through the Kubernetes API server. Operations like `session_workspace_exists` (a single `[ -d ... ]` check) pay the full handshake cost. For file reads, `read_file` base64-encodes inside the pod and decodes on the api-server side just to transport binary data through the text WebSocket channel. A direct HTTP call to the pod IP is faster and supports binary bodies natively.

**`pods/exec` RBAC is overpowered.** The api-server service account needs `pods/exec` solely because of these operations. Removing it reduces the blast radius of a compromised api-server pod. The remaining use of `k8s_stream` (ACP agent communication) can transition to a different mechanism long-term.

**Fragile binary transport.** `upload_file` creates a tar archive in memory, opens a WebSocket with `_preload_content=False`, writes tar bytes to stdin, then loops `ws_client.update(timeout=30)` to collect stdout. The K8s Python client cannot signal EOF on stdin without closing the entire WebSocket, so the shell script uses `head -c <size>` as a workaround. An HTTP POST with a binary body is straightforward.

## Important Notes

**The ACP exec client is special and stays on `k8s_stream`.** `ACPExecClient` (`kubernetes/internal/acp_exec_client.py`) uses a persistent WebSocket for bidirectional JSON-RPC streaming with the `opencode acp` subprocess. This is fundamentally different from the request/response operations being migrated — it cannot use simple HTTP because the agent's stdio protocol requires a persistent bidirectional channel and streaming ACP events need push semantics. Once all other `k8s_stream` usage is removed, ACP communication becomes the sole reason for `pods/exec` RBAC and can be addressed separately.

**The health check in `ACPExecClient.health_check` uses `k8s_stream` for a simple `echo ok` exec.** This should migrate to the daemon's existing `GET /health` endpoint instead.

**Snapshot restore is functionally a fresh session setup, not a live update.** When `restore_snapshot` runs, the agent is not yet attached to the session — restore is what happens *before* the session becomes interactive. That means config writes during restore have no concurrent reader and don't need atomic-swap semantics. `/session/setup` and `/session/restore` differ only in their initial state (empty dir + template copy vs. extracted snapshot); both are pre-agent and can write config files directly.

**The daemon currently restricts writes to `/workspace/managed/` via `ALLOWED_PREFIX` in `extract.py`.** The push endpoint's `safe_extract_then_atomic_swap` hard-rejects any `mount_path` outside this prefix. New endpoints that operate on `/workspace/sessions/` need their own path validation, sharing the same primitives (UTF-8 check, no symlinks/special files, no path traversal, size caps) but rooted at `/workspace/sessions/`.

**`write_sandbox_file` is dead code and should be deleted, not migrated.** It's declared on `SandboxManager` (`base.py`), implemented in both K8s and local backends, and stubbed in tests — but has zero production callers. It predates `/push` and was never wired into the skills writer. Delete the abstract method, both impls, and the stub state in `tests/common/craft/stubs.py`. No replacement endpoint needed.

**Existing built-in skills will be reimplemented via the new skills system.** The current built-in skills (pptx, image-generation, bio-builder, company-search) are baked into the sandbox Docker image under `/workspace/skills/` and symlinked into each session at setup time. This build-time baking + per-session symlinking approach goes away once the skills feature lands. Instead, all skills (built-in and custom) will be pushed to sandboxes at runtime via `push_to_sandbox` / `push_to_sandboxes` using the daemon's existing `/push` endpoint (see `skills-requirements.md` section 5, "Sandbox Delivery"). This means the daemon migration does not need to preserve the symlinking behavior long-term — the `/session/setup` endpoint creates the symlink in the interim, and the push system takes over once the skills feature is complete.

**The local backend needs no changes.** `LocalSandboxManager` handles all operations directly via the filesystem (`pathlib`, `shutil`, `subprocess`). Each abstract method already has a trivial local implementation. The local backend is already the target state that the K8s backend is catching up to.

## Catalog of `k8s_stream` Operations

Every method in `KubernetesSandboxManager` that currently calls `k8s_stream`:

| Method | What it does | Migration target |
|---|---|---|
| `setup_session_workspace` | Creates session dir, copies template, npm install, symlinks skills, writes AGENTS.md + opencode.json + org_info, starts Next.js | `POST /session/setup` (single call carrying config payload) |
| `_regenerate_session_config` | Writes AGENTS.md + opencode.json (called by `restore_snapshot`) | Folded into `POST /session/restore` |
| `restore_snapshot` | `aws s3 cp` + tar extract, config regen, Next.js start | `POST /session/restore` (single call; agent not yet running, so no atomicity concern) |
| `health_check` (via `ACPExecClient`) | `echo ok` via exec | Existing `GET /health` |
| `cleanup_session_workspace` | Kills Next.js PID, removes session dir | `POST /session/cleanup` |
| `session_workspace_exists` | `[ -d ... ]` check | `GET /session/exists` |
| `list_directory` | `ls -laL` + parse output | `GET /files/list` |
| `read_file` | `base64 <file>` + decode | `GET /files/read` |
| `upload_file` | Tar via stdin WebSocket | `POST /files/upload` |
| `delete_file` | `rm` via exec | `DELETE /files/delete` |
| `get_upload_stats` | `find` + `du` via exec | `GET /files/stats` |
| `generate_pptx_preview` | Runs `preview.py` script | `POST /pptx/preview` |
| `_ensure_agents_md_attachments_section` | Reads/modifies AGENTS.md via awk | `POST /agents-md/ensure-attachments` |
| `create_snapshot` | Tars outputs+attachments, pipes to `aws s3 cp` | Existing `POST /snapshot/create` |
| `write_sandbox_file` | `printf > file` to sandbox root | **Delete — dead code, no callers** |

**Not migrated:** `ACPExecClient.start` / `send_message` — persistent WebSocket for ACP JSON-RPC.

## Implementation Strategy

Move every `k8s_stream` operation (except ACP) to the daemon. After this lands, the only remaining `k8s_stream` usage is the ACP exec client.

### Auth

All new endpoints reuse the existing Ed25519 signature scheme already used by `/push`, `/snapshot/create`, and `/snapshot/restore`. The signed message is `{timestamp}|{path_or_endpoint}|{sha256_hex_of_body}`, verified against `ONYX_SANDBOX_PUSH_PUBLIC_KEY`. The "Bearer token" line in earlier drafts is obsolete — there is no second auth scheme.

### Session lifecycle endpoints

`/session/setup` and `/session/restore` carry the full session config payload (AGENTS.md, opencode.json, org_info contents) in their request body. The daemon writes those files directly as part of setup. No separate `/write-files` endpoint — config writes are always paired with structural setup, and both setup and restore run before the agent attaches, so atomic-swap semantics are unnecessary.

```
POST /session/setup
Body: {
  "session_id": "<uuid>",
  "nextjs_port": <int|null>,
  "agents_md": "<content>",
  "opencode_json": "<content>",
  "org_info": {"AGENTS.md": "...", "user_identity_profile.txt": "...", "organization_structure.json": "..."} | null,
  "copy_outputs_template": true,
  "npm_install": true,
  "symlink_managed_skills": true
}
→ Creates session dir, copies outputs template, runs npm install, symlinks
  .opencode/skills → /workspace/managed/skills, writes AGENTS.md +
  opencode.json + org_info/*, starts Next.js if port given.
→ 200 {"status": "ok"} or 4xx/5xx on validation/setup failure.

POST /session/cleanup
Body: {"session_id": "<uuid>"}
→ Kills Next.js by PID file, removes session directory.
→ 200 {"status": "ok"}

GET /session/exists?session_id=<uuid>
→ 200 {"exists": true|false}

POST /session/restore
Body: {
  "session_id": "<uuid>",
  "tenant_id": "<id>",
  "s3_bucket": "<bucket>",
  "storage_path": "<path>",
  "nextjs_port": <int|null>,
  "agents_md": "<content>",
  "opencode_json": "<content>",
  "check_node_modules": true
}
→ Downloads snapshot from S3 + extracts (reuses existing snapshot machinery),
  writes AGENTS.md + opencode.json, starts Next.js if port given and
  node_modules check passes.
→ 200 {"status": "ok"}
```

`/snapshot/restore` (raw S3 → disk extract) and `/snapshot/create` stay as-is. `/session/restore` is a higher-level wrapper that calls into the snapshot extract internally and then handles config writes + Next.js start.

### File operations + misc endpoints

```
GET    /files/list?session_id=<uuid>&path=<rel>     → JSON array of directory entries
GET    /files/read?session_id=<uuid>&path=<rel>     → binary body with Content-Type
POST   /files/upload?session_id=<uuid>              → multipart, returns {"filename": "..."}
DELETE /files/delete?session_id=<uuid>&path=<rel>   → {"deleted": true|false}
GET    /files/stats?session_id=<uuid>               → {"file_count", "total_size"}
POST   /pptx/preview                                → {"cached", "slides": [...]}
POST   /agents-md/ensure-attachments                → {"result": "added"|"exists"}
```

All file endpoints resolve paths relative to `/workspace/sessions/{session_id}/` and apply the same validation primitives as `extract.py` (no traversal, no symlinks, size caps). The session_id-as-query-param shape prevents callers from poking into arbitrary pod paths via the daemon.

### K8s manager changes

Every `k8s_stream` call in `KubernetesSandboxManager` (except ACP) gets replaced with an HTTP call to the daemon:

- `setup_session_workspace`: one `POST /session/setup` carrying config payload.
- `restore_snapshot`: one `POST /session/restore` carrying config payload (replaces the existing `/snapshot/restore` + `_regenerate_session_config` + start-Next.js sequence).
- `_regenerate_session_config`: deleted — folded into `/session/restore`.
- `health_check`: existing `GET /health` HTTP call (replaces `ACPExecClient.health_check` exec).
- `cleanup_session_workspace`: `POST /session/cleanup`.
- `session_workspace_exists`: `GET /session/exists`.
- `list_directory`: `GET /files/list`.
- `read_file`: `GET /files/read`.
- `upload_file`: `POST /files/upload`.
- `delete_file`: `DELETE /files/delete`.
- `get_upload_stats`: `GET /files/stats`.
- `generate_pptx_preview`: `POST /pptx/preview`.
- `_ensure_agents_md_attachments_section`: `POST /agents-md/ensure-attachments`.
- `create_snapshot`: existing `POST /snapshot/create` (already migrated).
- `write_sandbox_file`: deleted from base + both impls + stub.

**No new abstract methods on `SandboxManager`.** The daemon endpoints are internal implementation details of the K8s backend. These map to existing abstract methods — the K8s implementation just changes its transport.

### Future: Sidecar isolation

The daemon currently runs in the main container alongside the coding agent. If the agent is compromised, it could tamper with the daemon. This is acceptable because:

1. The daemon is not a trust boundary against the agent — the agent already has full access to the same filesystem.
2. The shared secret authenticates api-server → daemon, not the reverse. A compromised agent could read the secret, but can only call endpoints that write to its own filesystem.
3. The real security boundary is between pods (NetworkPolicy + namespace isolation), not between processes within a pod.

**When to move to a sidecar:** if the daemon ever becomes a trust boundary against the agent (e.g., enforcing per-session access control the agent must not bypass, or validating agent outputs before they leave the pod). The sidecar would share only a mounted volume, and the secret would be mounted only into the sidecar container. The daemon code and API stay the same — it's a pod-spec change.

## Daemon API Summary

All endpoints require an Ed25519 signature over `{timestamp}|{path_or_endpoint}|{sha256_hex_of_body}` in the `X-Push-Signature` + `X-Push-Timestamp` headers.

| Endpoint | Replaces |
|---|---|
| `GET /health` | `ACPExecClient.health_check` |
| `POST /push` | `write_files_to_sandbox` (atomic swap, skills) |
| `POST /session/setup` | `setup_session_workspace` (dir + template + npm + config + Next.js) |
| `POST /session/cleanup` | `cleanup_session_workspace` |
| `GET /session/exists` | `session_workspace_exists` |
| `POST /session/restore` | `restore_snapshot` (S3 extract + config + Next.js) |
| `GET /files/list` | `list_directory` |
| `GET /files/read` | `read_file` |
| `POST /files/upload` | `upload_file` |
| `DELETE /files/delete` | `delete_file` |
| `GET /files/stats` | `get_upload_stats` |
| `POST /pptx/preview` | `generate_pptx_preview` |
| `POST /snapshot/create` | `create_snapshot` |
| `POST /agents-md/ensure-attachments` | `_ensure_agents_md_attachments_section` |

## Tests

**Unit tests (daemon-side):**
- `test_daemon_session_lifecycle.py`: `/session/setup`, `/session/cleanup`, `/session/exists`, `/session/restore` against a temp directory with mocked S3. Verify config files written, directories created/removed, idempotency, signature rejection.
- `test_daemon_file_ops.py`: `/files/{list,read,upload,delete,stats}` against a temp session directory. Cover path-traversal rejection, missing-file behavior, binary content roundtrip.
- `test_daemon_agents_md.py`: `/agents-md/ensure-attachments` read-modify-write logic and idempotency.

**Integration test:**
- `test_daemon_e2e.py`: Spin up daemon with `TestClient`, exercise full session lifecycle (setup → file ops → cleanup) end-to-end without Kubernetes.

**K8s manager tests:**
- Update `tests/external_dependency_unit/craft/test_kubernetes_sandbox.py` and friends: mocks now expect signed HTTP calls (via `httpx`) instead of `k8s_stream`. Same observable behavior, different transport.
- `tests/common/craft/stubs.py`: remove `write_sandbox_file_*` counters and method; leave the rest as-is (the stub already mirrors `SandboxManager`'s abstract surface).

**Integration tests (`tests/integration/tests/craft/*`):**
- Only update tests that assert on shell-script side effects or mock `k8s_stream` directly. Tests that exercise the public HTTP API of the api-server (sessions, file uploads, etc.) should be unchanged.

## Key Files

- `kubernetes/kubernetes_sandbox_manager.py` — all `k8s_stream` calls except ACP get replaced with HTTP; `write_sandbox_file` deleted; `_regenerate_session_config` deleted.
- `kubernetes/docker/sandbox_daemon/server.py` — new endpoints added here.
- `kubernetes/docker/sandbox_daemon/extract.py` — existing safe-extract primitives reused; new module for session-rooted path validation.
- `kubernetes/internal/acp_exec_client.py` — stays on `k8s_stream`; health check migrates to daemon `/health`.
- `base.py` — `write_sandbox_file` abstract method removed.
- `local/local_sandbox_manager.py` — `write_sandbox_file` impl removed.
- `tests/common/craft/stubs.py` — `write_sandbox_file*` state removed.
