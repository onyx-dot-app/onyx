# Sandbox Daemon Expansion

Migrate all pod-side operations from `kubectl exec` (via `kubernetes.stream`) to the in-pod HTTP daemon on port 8731. Eliminates shell escaping fragility, WebSocket-per-call overhead, and the overpowered `pods/exec` RBAC permission from api-server's service account.

Companion doc: `sandbox-file-push.md` — describes the existing push primitive this plan builds on.

## Issues to Address

**Shell escaping is a correctness and security risk.** `setup_session_workspace` builds multi-line bash scripts with `printf '%s' '{agent_instructions_escaped}'` where the content has single quotes backslash-escaped. Any template change that introduces unexpected characters can silently corrupt the file or break the script. The same pattern repeats for `opencode.json`, `org_info/`, and the attachments section injection in `_ensure_agents_md_attachments_section`. Every new file written to the pod requires a new round of shell escaping.

**WebSocket setup per call is slow.** Each `k8s_stream` call negotiates a new WebSocket connection through the Kubernetes API server. Operations like `session_workspace_exists` (a single `[ -d ... ]` check) pay the full handshake cost. For file reads, `read_file` base64-encodes inside the pod and decodes on the api-server side just to transport binary data through the text WebSocket channel. A direct HTTP call to the pod IP is faster and supports binary bodies natively.

**`pods/exec` RBAC is overpowered.** The api-server service account needs `pods/exec` solely because of these operations. Removing it reduces the blast radius of a compromised api-server pod. The remaining use of `k8s_stream` (ACP agent communication) can transition to a different mechanism long-term.

**Fragile binary transport.** `upload_file` creates a tar archive in memory, opens a WebSocket with `_preload_content=False`, writes tar bytes to stdin, then loops `ws_client.update(timeout=30)` to collect stdout. The K8s Python client cannot signal EOF on stdin without closing the entire WebSocket, so the shell script uses `head -c <size>` as a workaround. An HTTP POST with a binary body is straightforward.

## Important Notes

**The ACP exec client is special and stays on `k8s_stream`.** `ACPExecClient` (`kubernetes/internal/acp_exec_client.py`) uses a persistent WebSocket for bidirectional JSON-RPC streaming with the `opencode acp` subprocess. This is fundamentally different from the request/response operations being migrated — it cannot use simple HTTP because the agent's stdio protocol requires a persistent bidirectional channel and streaming ACP events need push semantics. Once all other `k8s_stream` usage is removed, ACP communication becomes the sole reason for `pods/exec` RBAC and can be addressed separately.

**The health check in `ACPExecClient.health_check` uses `k8s_stream` for a simple `echo ok` exec.** This should migrate to the daemon's existing `GET /health` endpoint instead.

**The daemon currently restricts writes to `/workspace/managed/` via `ALLOWED_PREFIX` in `extract.py`.** The push endpoint's `safe_extract_then_atomic_swap` hard-rejects any `mount_path` outside this prefix. New endpoints that operate on `/workspace/sessions/` need their own path validation, not a relaxation of the existing push endpoint's allow-list.

**`write_sandbox_file` writes to the sandbox root** (e.g., `skills/company-search/SKILL.md`) visible to all sessions via symlinks. Currently uses `k8s_stream`. Can migrate to a new `/write-files` endpoint.

**Existing built-in skills will be reimplemented via the new skills system.** The current built-in skills (pptx, image-generation, bio-builder, company-search) are baked into the sandbox Docker image under `/workspace/skills/` and symlinked into each session at setup time. This build-time baking + per-session symlinking approach goes away once the skills feature lands. Instead, all skills (built-in and custom) will be pushed to sandboxes at runtime via `push_to_sandbox` / `push_to_sandboxes` using the daemon's existing `/push` endpoint (see `skills-requirements.md` section 5, "Sandbox Delivery"). This means the daemon migration does not need to preserve the symlinking behavior long-term — the `/write-files` endpoint covers the interim, and the push system takes over once the skills feature is complete.

**The local backend needs no changes.** `LocalSandboxManager` handles all operations directly via the filesystem (`pathlib`, `shutil`, `subprocess`). Each abstract method added to `SandboxManager` gets a trivial local implementation. The local backend is already the target state that the K8s backend is catching up to.

## Catalog of `k8s_stream` Operations

Every method in `KubernetesSandboxManager` that calls `k8s_stream`:

| Method | What it does |
|---|---|
| `setup_session_workspace` | Creates session dir, copies template, npm install, symlinks skills, writes AGENTS.md + opencode.json + org_info, starts Next.js |
| `_regenerate_session_config` | Writes AGENTS.md + opencode.json (called by `restore_snapshot`) |
| `write_sandbox_file` | `printf > file` to sandbox root |
| `health_check` (via `ACPExecClient`) | `echo ok` via exec |
| `cleanup_session_workspace` | Kills Next.js PID, removes session dir |
| `session_workspace_exists` | `[ -d ... ]` check |
| `restore_snapshot` | `aws s3 cp` + tar extract, config regen, Next.js start |
| `list_directory` | `ls -laL` + parse output |
| `read_file` | `base64 <file>` + decode |
| `upload_file` | Tar via stdin WebSocket |
| `delete_file` | `rm` via exec |
| `get_upload_stats` | `find` + `du` via exec |
| `generate_pptx_preview` | Runs `preview.py` script |
| `_ensure_agents_md_attachments_section` | Reads/modifies AGENTS.md via awk |
| `create_snapshot` | Tars outputs+attachments, pipes to `aws s3 cp` |

**Not migrated:** `ACPExecClient.start` / `send_message` — persistent WebSocket for ACP JSON-RPC.

## Implementation Strategy

Move every `k8s_stream` operation (except ACP) to the daemon in a single refactor. After this lands, the only remaining `k8s_stream` usage is the ACP exec client.

### New daemon endpoints

**`POST /write-files`** — direct file writes

```
POST /write-files
Headers: Authorization, Content-Type: application/gzip, X-Bundle-Sha256
Query: base_path (absolute, must resolve under /workspace/)
Body: tar.gz of files to write

200 → files written (direct write, no atomic swap)
400 → validation error
401 → auth error
```

Unlike `/push`, this endpoint writes files directly to the target directory without atomic symlink swap. Appropriate for session config files (AGENTS.md, opencode.json) that are written once during setup. Reuses the same safe-extract validation (no symlinks, no path traversal, no special files) but against `/workspace/` as the allowed prefix.

**Session lifecycle endpoints:**

```
POST /session/setup
Body: {"session_id", "nextjs_port", "copy_template", "npm_install"}
Creates session dir, copies outputs template, runs npm install, starts Next.js.

POST /session/cleanup
Body: {"session_id"}
Kills Next.js by PID file, removes session directory.

GET /session/exists?session_id=<uuid>
Returns {"exists": true|false}

POST /session/restore
Body: {"session_id", "s3_path", "nextjs_port", "check_node_modules"}
Downloads snapshot from S3, extracts, starts Next.js.

POST /nextjs/start
Body: {"session_id", "port", "check_node_modules"}
Returns {"pid": <int>}

POST /nextjs/stop
Body: {"session_id"}
```

**File operations + misc endpoints:**

```
GET    /files/list?path=<abs-path>     → JSON array of directory entries
GET    /files/read?path=<abs-path>     → binary body with Content-Type
POST   /files/upload                   → multipart, returns {"filename": "..."}
DELETE /files/delete?path=<abs-path>   → {"deleted": true|false}
GET    /files/stats?path=<abs-path>    → {"file_count", "total_size"}
POST   /pptx/preview                   → {"cached", "slides": [...]}
POST   /snapshot/create                → {"status": "created"|"empty"}
POST   /agents-md/ensure-attachments   → {"result": "added"|"exists"}
```

### K8s manager changes

Every `k8s_stream` call in `KubernetesSandboxManager` (except ACP) gets replaced with an HTTP call to the daemon:

- `setup_session_workspace`: (1) `POST /session/setup` for dir creation, template copy, npm install, Next.js start, then (2) `POST /write-files` for AGENTS.md, opencode.json, org_info. Two-call sequence: structural setup first, then config writes.
- `_regenerate_session_config`: Replace shell script with `POST /write-files`.
- `write_sandbox_file`: Replace `k8s_stream` with `POST /write-files`.
- `health_check`: Replace `ACPExecClient.health_check` exec with `GET /health` HTTP call to daemon.
- `cleanup_session_workspace`: `POST /session/cleanup`.
- `session_workspace_exists`: `GET /session/exists`.
- `restore_snapshot`: `POST /session/restore` + `POST /write-files` + `POST /nextjs/start`.
- `list_directory`: `GET /files/list`.
- `read_file`: `GET /files/read`.
- `upload_file`: `POST /files/upload`.
- `delete_file`: `DELETE /files/delete`.
- `get_upload_stats`: `GET /files/stats`.
- `generate_pptx_preview`: `POST /pptx/preview`.
- `_ensure_agents_md_attachments_section`: `POST /agents-md/ensure-attachments`.
- `create_snapshot`: `POST /snapshot/create`.

**No new abstract methods on SandboxManager.** The daemon endpoints are internal implementation details of the K8s backend. These map to existing abstract methods — the K8s implementation just changes its transport.

### Future: Sidecar isolation

The daemon currently runs in the main container alongside the coding agent. If the agent is compromised, it could tamper with the daemon. This is acceptable because:

1. The daemon is not a trust boundary against the agent — the agent already has full access to the same filesystem.
2. The shared secret authenticates api-server → daemon, not the reverse. A compromised agent could read the secret, but can only call endpoints that write to its own filesystem.
3. The real security boundary is between pods (NetworkPolicy + namespace isolation), not between processes within a pod.

**When to move to a sidecar:** if the daemon ever becomes a trust boundary against the agent (e.g., enforcing per-session access control the agent must not bypass, or validating agent outputs before they leave the pod). The sidecar would share only a mounted volume, and the secret would be mounted only into the sidecar container. The daemon code and API stay the same — it's a pod-spec change.

## Daemon API Summary

All endpoints require `Authorization: Bearer <secret>`.

| Endpoint | Replaces |
|---|---|
| `GET /health` | `ACPExecClient.health_check` |
| `POST /push` | `write_files_to_sandbox` (atomic swap) |
| `POST /write-files` | shell `printf` for config files |
| `POST /session/setup` | `setup_session_workspace` dir + template + npm |
| `POST /session/cleanup` | `cleanup_session_workspace` |
| `GET /session/exists` | `session_workspace_exists` |
| `POST /session/restore` | `restore_snapshot` S3 + extract |
| `POST /nextjs/start` | Next.js start in setup/restore |
| `POST /nextjs/stop` | Next.js stop in cleanup |
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
- `test_daemon_write_files.py`: Test `/write-files` path validation, tar.gz extraction, SHA-256 mismatch rejection. Same rigor as existing `test_safe_extract.py`.
- `test_daemon_endpoints.py`: Test each new endpoint using FastAPI's `TestClient`. Mock filesystem operations. Cover auth rejection, path validation, correct response shapes.

**Integration test:**
- `test_daemon_e2e.py`: Spin up daemon with `TestClient`, write real files to a temp directory, exercise the full write → read → list → delete → stats cycle without Kubernetes.

**K8s manager tests:**
- Update mocks to expect HTTP calls (via `httpx`) instead of `k8s_stream` calls. Same operations, different transport.

## Key Files

- `kubernetes/kubernetes_sandbox_manager.py` — all `k8s_stream` calls except ACP get replaced with HTTP
- `kubernetes/docker/daemon/server.py` — all new endpoints added here
- `kubernetes/docker/daemon/extract.py` — existing safe-extract; new `write.py` for `/write-files` path validation
- `kubernetes/internal/acp_exec_client.py` — stays on `k8s_stream`; health check migrates to daemon `/health`
- `base.py` — no new abstract methods needed
