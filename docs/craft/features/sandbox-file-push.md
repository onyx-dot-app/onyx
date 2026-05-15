# Sandbox File Push

Shared primitive for writing files from api_server into running sandbox pods. Consumed by skills, user-uploaded files, agent instructions (AGENTS.md / opencode.json), and any future per-pod content. Replaces the ad-hoc `kubectl exec` bash heredoc in `setup_session_workspace`.

## 1. Goal

One callable for any feature to land files in running sandboxes — exposed as a method on the existing `SandboxManager`:

```python
sandbox_ids = get_active_sandbox_ids_for_users(affected_user_ids, db_session)
sandbox_files = {sid: build_skills_files_for_user(user, db_session) for sid, user in ...}
get_sandbox_manager().push_to_sandboxes(
    mount_path="/workspace/managed/skills",
    sandbox_files=sandbox_files,
)
```

The feature owns *what*, *when*, and *which sandboxes*. The caller queries the DB for affected users' sandbox_ids, builds the sandbox_id-to-files mapping, and calls `push_to_sandboxes`. `SandboxManager` handles parallel fan-out, atomic swap, retry, and (on k8s) auth.

## 2. Non-goals

- Cross-cluster pushes. api_server and sandbox pods share a VPC.
- File-watcher / per-byte streaming. Bundles are coarse-grained snapshots.
- Versioning, rollback, or content history.
- Strong consistency. Mutations are eventually consistent.
- Bundle authoring — features compute their own bytes.

## 3. Architecture

```
        ┌───────────────────────────────────┐
        │ api_server                        │
        │                                   │
        │  feature mutation handler         │
        │       │                           │
        │       ▼                           │
        │  SandboxManager.push_to_sandboxes  │
        │   1. ThreadPoolExecutor:          │
        │      parallel push_to_sandbox     │
        │      per sandbox_id               │
        └───────┬──────────┬──────────┬─────┘
                │          │          │
                ▼          ▼          ▼
        ┌─────────┐  ┌─────────┐  ┌─────────┐
        │ pod A   │  │ pod B   │  │ pod C   │
        │ main:   │  │ main:   │  │ main:   │
        │ opencode│  │ opencode│  │ opencode│
        │ + bg    │  │ + bg    │  │ + bg    │
        │ push    │  │ push    │  │ push    │
        │ daemon  │  │ daemon  │  │ daemon  │
        │ :8731   │  │ :8731   │  │ :8731   │
        └─────────┘  └─────────┘  └─────────┘
```

Three pieces:

1. **`SandboxManager` push API** — `push_to_sandbox` and `push_to_sandboxes` ship as concrete default methods on the existing `SandboxManager` ABC (`backend/onyx/server/features/build/sandbox/base.py`). They own parallel fan-out via `ThreadPoolExecutor`, per-target retry with exponential backoff, and result aggregation. Backend-agnostic — the same code runs whether the manager is k8s, local, or future docker-compose. Callers own user-to-sandbox resolution (DB queries) and pass sandbox_id-keyed mappings.
2. **One new abstract method on `SandboxManager`** — `write_files_to_sandbox(*, sandbox_id, mount_path, files)`. Subclasses implement this. Kubernetes does tar.gz + HTTP to the in-pod daemon; local writes to the sandbox directory directly via `shutil`.
3. **In-pod push daemon (k8s only)** — small FastAPI/uvicorn process running alongside opencode in each sandbox pod's main container. One endpoint: `POST /push`. Not present in local or docker-compose backends.

## 3.1 Backends

The push API lives on `SandboxManager` (`backend/onyx/server/features/build/sandbox/base.py`), selected at runtime via `SANDBOX_BACKEND`. Two methods are concrete on the base class (`push_to_sandbox`, `push_to_sandboxes`) and shared across all backends. One new abstract method carries the per-backend work:

```python
class SandboxManager(ABC):
    @abstractmethod
    def write_files_to_sandbox(
        self, *, sandbox_id: str, mount_path: str, files: dict[str, bytes],
    ) -> None: ...
```

| Backend | `write_files_to_sandbox` does |
|---|---|
| **Kubernetes (v1)** | Builds tar.gz, looks up pod IP, HTTP POST to in-pod daemon, daemon does safe-extract + atomic swap. §5 / §6 / §9.1 / §9.2 describe this path. |
| **Local (v1)** | Writes directly to `$SANDBOX_ROOT/<sandbox_id>/sessions/<session_id>/<mount_path>/` via `shutil`. Atomic swap (§7) still applies. No daemon, no networking, no auth, no NetworkPolicy. ~20 LOC. |
| **Docker-compose (future, not v1)** | Bind-mount a host dir into the container and write to the host dir, or `docker exec`. Same shape; lands when we need it. |

Section applicability:

| Section | K8s | Local | Docker-compose (future) |
|---|---|---|---|
| §4 caller-facing API | ✓ | ✓ | ✓ |
| §5 wire format & daemon | ✓ | — | TBD |
| §6 pod spec & supervisor | ✓ | — | TBD |
| §7 atomic swap | ✓ | ✓ | ✓ |
| §8 cold-start & wakeup | ✓ | ✓ | ✓ |
| §9.1 NetworkPolicy | ✓ | — | TBD |
| §9.2 shared secret | ✓ | — | TBD |
| §9.3 safe extract | ✓ | hygiene applies, no untrusted bytes | TBD |
| §10 multi-tenancy | ✓ | ✓ | ✓ |

## 4. Push API on `SandboxManager`

The push API is **synchronous**, matching Onyx's codebase conventions (sync FastAPI routes, sync `httpx.Client` via `HttpxPool`, sync `kubernetes` Python SDK). Per-target parallelism uses `concurrent.futures.ThreadPoolExecutor`. The two concrete `push_*` methods are **on the ABC** — the same default implementation runs for every backend. Subclasses implement only the abstract primitive `write_files_to_sandbox`.

```python
# backend/onyx/server/features/build/sandbox/models.py

class PushFailure(BaseModel):
    sandbox_id: str
    reason: str                  # "timeout" | "write_error" | "not_found"
    detail: str | None = None

class PushResult(BaseModel):
    targets: int
    succeeded: int
    failures: list[PushFailure]

class RetriableWriteError(Exception):
    """Raised by write_files_to_sandbox for transient failures (timeout, pod
    not-ready, etc). Triggers the retry loop in the base class."""

class FatalWriteError(Exception):
    """Raised by write_files_to_sandbox for permanent failures (validation,
    auth). Skips retry and records the failure."""

# backend/onyx/server/features/build/sandbox/base.py

class SandboxManager(ABC):
    # ---- Concrete defaults; shared across backends ----
    def push_to_sandbox(
        self, *,
        sandbox_id: str,
        mount_path: str,
        files: dict[str, bytes],
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Single-target push with retry. Wraps write_files_to_sandbox
        with exponential backoff for RetriableWriteError."""

    def push_to_sandboxes(
        self, *,
        mount_path: str,
        sandbox_files: dict[str, dict[str, bytes]],
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Parallel fan-out over push_to_sandbox. Takes a sandbox_id → files
        mapping. Caller owns user → sandbox resolution (DB queries)."""

    # ---- Backend-specific; one abstract method ----
    @abstractmethod
    def write_files_to_sandbox(
        self, *, sandbox_id: str, mount_path: str, files: dict[str, bytes],
    ) -> None:
        """Write atomically. Raise RetriableWriteError for transients,
        FatalWriteError for permanent failures."""
```

Semantics:

- **`SandboxManager` owns parallelism and retry.** Callers never loop over targets.
- **Caller owns sandbox resolution.** The caller (skills API, session setup, etc.) queries the DB for affected users' sandbox_ids, builds the `sandbox_id → files` mapping, and passes it to `push_to_sandboxes`. `SandboxManager` never needs to know about users or tenants for push purposes.
- `push_to_sandboxes` `ThreadPoolExecutor`-maps `push_to_sandbox` across the entries in `sandbox_files`. Each sandbox_id gets its own file set. One entry = single sandbox update; many entries = fan-out.
- `push_to_sandbox` wraps `write_files_to_sandbox` with retry. Used directly for session-scoped content (e.g. AGENTS.md) or called internally by `push_to_sandboxes`.
- Files at `mount_path` are **replaced as a unit**. Anything not in the `files` dict disappears at that path on the target.
- Targets that raise `RetriableWriteError` are retried in-process with exponential backoff up to ~30 s, then recorded in `failures` and logged. `FatalWriteError` skips retry. **No background task system in v1** — every push is a full snapshot of `mount_path`, so the next mutation (or cold-start/wakeup hydration) re-converges any target that missed one.
- v1 caps total bundle size at 100 MiB summed across all entries. All foreseeable v1 consumers (skills bundles, user_library uploads in the low-MB range, AGENTS.md / opencode.json) fit comfortably under this cap.

## 5. Wire format & in-pod daemon — *Kubernetes backend only*

This entire section describes the k8s `write_files_to_sandbox` implementation. Local backend writes directly via `shutil`; no daemon, no wire format. Docker-compose (future) likely lands somewhere between the two.

The daemon is a small Python module (FastAPI + uvicorn) packaged into the existing sandbox image. Python is already in the image; daemon dependencies are added to the sandbox image's `initial-requirements.txt`. One endpoint:

```
POST /push?mount_path=<abs-path-inside-sandbox>
Headers:
  Authorization: Bearer <shared-secret>
  Content-Type:  application/gzip
  X-Bundle-Sha256: <hex sha256 of the raw body>
Body: tar.gz bytes (single archive containing the files)

200 OK            → bundle accepted, swap complete
400 Bad Request   → hash mismatch / malformed archive / safe-extract violation
401 Unauthorized  → shared secret missing or invalid
413 Payload Too Large → exceeds size cap
```

```python
@app.post("/push")
def push(
    request: Request,
    mount_path: str = Query(...),
    authorization: str = Header(...),
    x_bundle_sha256: str = Header(...),
) -> dict:
    verify_shared_secret(authorization)        # hmac.compare_digest against env
    body = request.body()                      # bounded by MAX_BUNDLE_BYTES
    if hashlib.sha256(body).hexdigest() != x_bundle_sha256:
        raise HTTPException(400, "bundle hash mismatch")
    safe_extract_then_atomic_swap(body, mount_path)
    return {"status": "ok"}
```

`HTTPException` is fine here — the daemon is a separate FastAPI app, not part of api_server. The `OnyxError` convention is for the main api_server's routes.

### Wire format

- **Body**: single `tar.gz` blob built by the k8s manager from the caller's `files` dict; daemon extracts with Python's `tarfile`. Not multipart, not zip.
- **Integrity**: manager computes sha256 of the raw body and sends as `X-Bundle-Sha256`. Daemon recomputes after receive and rejects on mismatch. Catches truncation/corruption without trusting the network path.
- **Size cap**: `MAX_BUNDLE_BYTES = 100 MiB` enforced on the request `Content-Length` before reading.

### Surface details

- Binds `0.0.0.0:8731` on a cluster-internal port (no NodePort, no Ingress, not exposed via Service).
- Stateless. Crash recovery is "supervisor restarts the daemon" (§6).
- ~150 LOC plus the safe-extract module (§9).

## 6. Pod spec & process supervision — *Kubernetes backend only*

Changes in `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:_create_sandbox_pod`:

- **Labels**: `onyx.app/tenant-id`, `onyx.app/user-id`, `onyx.app/sandbox-id`.
- **Env var**: `ONYX_SANDBOX_PUSH_SECRET` via `V1EnvVar.value_from=V1EnvVarSource(secret_key_ref=...)` — mounted from the shared `onyx-sandbox-push-secret` k8s Secret (same Secret in api_server pods).
- **Container port**: expose 8731 (cluster-internal only).
- **Entrypoint**: changes from `CMD ["sleep", "infinity"]` to a supervisor (§6.1).

### 6.1 Supervisor — required, not optional

The current sandbox image entrypoint is `CMD ["sleep", "infinity"]`; all work happens via `kubectl exec`. There is **no process supervisor** today. The daemon and opencode must be lifecycle-independent: an opencode crash must not stop the daemon, and a daemon crash must not stop opencode. This forces a supervisor into the image.

v1 picks the smallest thing that works: a bash entrypoint script that backgrounds both processes and restarts each independently on exit, with a `trap` to clean up on SIGTERM. `tini -p` or `s6-overlay` are credible upgrades if the bash path proves brittle.

```bash
# /workspace/entrypoint.sh — invoked by Dockerfile ENTRYPOINT
#!/bin/bash
set -e
trap 'kill 0 2>/dev/null; exit' SIGTERM SIGINT

start_daemon() {
  while true; do
    /workspace/.venv/bin/python -m push_daemon.server
    sleep 1
  done
}

start_opencode_runner() {
  # placeholder for whatever currently runs opencode-on-demand;
  # if today's behavior is "wait for kubectl exec", keep that here.
  sleep infinity
}

start_daemon &
start_opencode_runner &
wait
```

Whether opencode itself auto-restarts on crash today is a pre-existing concern this primitive surfaces; the bash supervisor above makes it possible to add later without further infra work.

## 7. Atomic swap

The daemon never writes into a live mount path. It writes to a fresh versioned dir, then atomic-renames a symlink onto the live path.

```
/workspace/managed/skills          -> .versions/20260514T120000Z-abc123  (current)
/workspace/managed/.versions/
    20260514T120000Z-abc123/       (live, fully populated)
    20260514T130000Z-def456/       (new, being written)
```

Sequence per push:

1. Extract tarball into `.versions/<ts>-<sha>/`.
2. Create a temporary symlink (`skills.tmp`) pointing to the new dir.
3. `os.rename("skills.tmp", "skills")` — atomic on POSIX. Readers either see the old or new symlink target, never an in-between state.
4. Schedule deletion of the old versioned dir after a 60 s grace period.

Two POSIX guarantees do the work: `rename` of a symlink is atomic; open file handles into a replaced inode remain valid until closed. In-flight reads finish against the old content; new opens see new content; nothing tears. `ln -sfn` is *not* atomic — the temp-rename pattern is what makes this safe.

## 8. Cold-start & wakeup hydration

When a sandbox is provisioned (k8s pod created, or local sandbox dir created) `/workspace/managed/` is empty. Each feature exposes a `push_to_pod(sandbox_id, user, db_session)` helper that builds its current file set for the user and calls `get_sandbox_manager().push_to_sandbox(...)`. `SandboxManager.setup_session_workspace` calls each helper after the sandbox is ready:

```python
skills.push_to_pod(sandbox_id, user, db_session)
user_library.push_to_pod(sandbox_id, user, db_session)
agent_instructions.push_to_pod(sandbox_id, session, db_session)
```

There is no separate "session start" code path in the shared infra — the existing one stays, it just routes through `SandboxManager.push_to_sandbox` instead of `kubectl exec`-ing bash.

**Wakeup** (snapshot pod restored from suspended state) takes the same path: the wakeup hook in `SandboxManager` calls the same `push_to_pod` helpers to catch the sandbox up to current state. The snapshot may have been taken seconds or hours ago; intervening mutations are re-applied by the hydration call. No separate "wakeup-only" code path.

This makes mutation push the *optimization* for "deliver changes live to a warm sandbox" and cold-start/wakeup hydration the *correctness floor*. Even if every mutation push fails, the next cold-start or wakeup re-converges from current DB state.

## 9. Security

Three layers, all required:

### 9.1 NetworkPolicy (primary defense) — *Kubernetes backend only*

A NetworkPolicy restricts ingress on sandbox-pod port 8731 to api_server pods only. Sandbox pods cannot reach each other on this port; nothing outside the api_server pod selector can either. This is the load-bearing defense.

No NetworkPolicies exist in the Helm chart today (verified). A new template at `deployment/helm/charts/onyx/templates/network-policy-sandbox-push.yaml`:

```yaml
{{- if .Values.sandboxPush.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "onyx.fullname" . }}-sandbox-push
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: sandbox
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: onyx-api-server
      ports:
        - protocol: TCP
          port: 8731
{{- end }}
```

### 9.2 Shared secret (defense in depth) — *Kubernetes backend only*

A single long-random secret lives in k8s Secret `onyx-sandbox-push-secret`, mounted as env var `ONYX_SANDBOX_PUSH_SECRET` in both api_server and every sandbox pod. `KubernetesSandboxManager.write_files_to_sandbox` sends `Authorization: Bearer ${ONYX_SANDBOX_PUSH_SECRET}`; the daemon `hmac.compare_digest`s the incoming header against its local copy and rejects with 401 on mismatch. `hmac.compare_digest` (not `==`) avoids timing side channels.

Rotation: update the Secret and roll api_server + sandbox pods. v1 does not hot-reload.

### 9.3 Safe extract (load-bearing security boundary)

`safe_extract_then_atomic_swap` is the only thing standing between a credentialed attacker (or a buggy feature) and arbitrary filesystem writes inside the pod. Lives in `backend/onyx/server/features/build/sandbox/kubernetes/docker/daemon/extract.py` and must reject:

- **Path traversal**: any entry whose normalized path escapes the bundle root, including `..` components and absolute paths.
- **Symlinks and hard links**: bundles ship regular files only (reject `TarInfo.issym() or TarInfo.islnk()`).
- **Special files**: device nodes, FIFOs, sockets, block devices.
- **Writes outside `/workspace/managed/`**: hard allow-list check on the resolved final path.
- **Per-entry size > `MAX_FILE_BYTES` (25 MiB)** and **total uncompressed size > `MAX_BUNDLE_BYTES` (100 MiB)**.
- **Non-UTF-8 path names** (defensive; avoids surprises with shell tooling that reads the dir).

`backend/onyx/skills/bundle.py` is currently an empty stub (no shared helper to reuse). The safe-extract logic ships fresh in `kubernetes/docker/daemon/extract.py`; if validation needs surface elsewhere later, factor out then.

### 9.4 Why not per-pod JWTs in v1

The specific threat per-pod JWTs defend against is lateral movement — a compromised sandbox pod replaying its token to attack a sibling sandbox. §9.1 already blocks that path. The remaining threat (compromised api_server feature pushing to the wrong tenant) is not mitigated by either scheme. If the threat model ever calls for per-pod identity, JWTs slot in behind the same `Authorization` header without changing the daemon's API.

## 10. Multi-tenancy

1. **Tenant isolation is the caller's responsibility.** The push API (`push_to_sandbox`, `push_to_sandboxes`) accepts sandbox_ids directly and has no concept of tenants. Callers query tenant-scoped DB tables (which the existing schema/middleware ensure are tenant-isolated) to resolve sandbox_ids, then pass them to the push API. The push API cannot accidentally target sandboxes outside the caller's tenant because the DB queries never return them.
2. **Trust boundary**: the k8s daemon trusts any api_server-authenticated caller. Cross-tenant misrouting is prevented by the caller's tenant-scoped DB queries and code review of the calling features, not by daemon-side validation or push-API-level tenant checks.

## 11. Feature integration

### Skills

Single-user grant change. The caller queries for sandbox_ids, builds the mapping, and calls `push_to_sandboxes`:

```python
sandbox_ids = get_active_sandbox_ids_for_users([user.id], db_session)
sandbox_files = {sid: build_skills_files_for_user(user, db_session) for sid in sandbox_ids}
get_sandbox_manager().push_to_sandboxes(
    mount_path="/workspace/managed/skills",
    sandbox_files=sandbox_files,
)
```

Org-wide change (`is_public=True` upload, public-skill edit, builtin availability flip):

```python
user_sandbox_map = get_active_sandboxes_for_tenant_users(db_session)
sandbox_files = {
    sid: build_skills_files_for_user(user, db_session)
    for sid, user in user_sandbox_map.items()
}
get_sandbox_manager().push_to_sandboxes(
    mount_path="/workspace/managed/skills",
    sandbox_files=sandbox_files,
)
```

`build_skills_files_for_user` lives in `backend/onyx/skills/push.py`. It walks built-ins (rendering `SKILL.md.template` against this user's `SkillRenderContext`) and custom skills the user has access to, returning a flat path-to-bytes dict.

### User library and agent instructions

- **User library**: same pattern. `mount_path="/workspace/managed/user_library"`, helper at `backend/onyx/user_files/push.py` (or equivalent).
- **Agent instructions**: uses `push_to_sandbox` because content is session-scoped (per-session AGENTS.md / opencode.json). `mount_path="/workspace/managed/agent_instructions"`, helper co-located with the existing agent-instruction generation code.

## 12. File structure

### New code

Co-located with the sandbox feature under `backend/onyx/server/features/build/sandbox/`:

```
backend/onyx/server/features/build/sandbox/
├── models.py           # PushResult, PushFailure, FileSet,
│                       #   RetriableWriteError, FatalWriteError
│                       #   (merged with existing SandboxInfo, LLMProviderConfig, etc.)
├── base.py             # push_to_sandbox + push_to_sandboxes (concrete) + 1 abstract method
├── kubernetes/
│   ├── kubernetes_sandbox_manager.py  # write+find via tarball+HTTP;
│   │                                  #   _build_targz, _build_push_auth_header (private)
│   └── docker/
│       └── daemon/     # in-pod push daemon — self-contained, no onyx.* imports,
│           ├── server.py   # FastAPI app on :8731  (invoked as `python -m push_daemon.server`)
│           └── extract.py  # safe_extract_then_atomic_swap + reject-list checks
└── local/local_sandbox_manager.py     # write+find via shutil
```

No `pusher.py` module — `push_to_sandbox` and `push_to_sandboxes` are concrete methods on `SandboxManager`'s base class (§4). Push types (`PushResult`, `PushFailure`, etc.) live in `models.py` alongside the existing sandbox models. Tarball building (`_build_targz`) and auth header construction (`_build_push_auth_header`) are private functions in `kubernetes_sandbox_manager.py`, not separate modules. The daemon is a self-contained package under `kubernetes/docker/daemon/` with no `onyx.*` imports; it is copied to `/workspace/push_daemon/` in the sandbox image. The local implementation uses only `shutil` + `os.rename` for atomic swap; no daemon dependency.

### Per-feature push helpers

Co-located with each feature:

```
backend/onyx/skills/push.py                    # build_skills_files_for_user, push_to_pod
backend/onyx/user_files/push.py                # (analogous)
backend/onyx/server/features/build/.../push.py # agent_instructions (or wherever AGENTS.md is built today)
```

### Sandbox image

```
backend/onyx/server/features/build/sandbox/kubernetes/docker/
├── Dockerfile                       # MODIFY: add entrypoint.sh, daemon deps, /workspace/managed
├── entrypoint.sh                    # NEW: supervisor (§6.1)
└── initial-requirements.txt         # MODIFY: add fastapi, uvicorn
```

Dockerfile changes:
- Add `fastapi` and `uvicorn[standard]` to `initial-requirements.txt`.
- Copy the `daemon/` directory into the image at `/workspace/push_daemon/` (self-contained; no `onyx.*` imports needed).
- `mkdir /workspace/managed` at build time, chowned to the sandbox user.
- Replace `CMD ["sleep", "infinity"]` with `ENTRYPOINT ["/workspace/entrypoint.sh"]`.

### Sandbox managers

**`base.py`** — add one abstract method:
- `write_files_to_sandbox(*, sandbox_id, mount_path, files) -> None`

**`kubernetes_sandbox_manager.py`**:
- Implement `write_files_to_sandbox` using `CoreV1Api` + tar.gz + HTTP to the in-pod daemon.
- Modifications in `_create_sandbox_pod`: add labels (§6), add `ONYX_SANDBOX_PUSH_SECRET` env var via `V1EnvVarSource.secret_key_ref`, expose container port 8731.

**`local_sandbox_manager.py`**:
- Implement `write_files_to_sandbox` using `shutil` writes and `os.rename` for atomic swap.

**Both managers** — modifications in `setup_session_workspace`:
- Call each feature's `push_to_pod(...)` instead of writing AGENTS.md / opencode.json / skills via the existing bash heredoc (k8s) or direct file writes (local).
- Same call at the wakeup hook (§8).

### Helm chart

```
deployment/helm/charts/onyx/
├── templates/
│   └── network-policy-sandbox-push.yaml  # NEW (§9.1) — only new file
└── values.yaml                              # MODIFY
```

`values.yaml` changes — no new template file for the secret:
- Add `auth.sandboxPushSecret` entry alongside existing `auth.postgresql`, `auth.redis`, etc. The existing `templates/auth-secrets.yaml` loops over `.Values.auth.*` and emits the k8s Secret automatically. The api_server deployment already wires `auth.*` entries into env vars via the `onyx.envSecrets` helper, so api_server picks up `ONYX_SANDBOX_PUSH_SECRET` for free.

```yaml
auth:
  sandboxPushSecret:
    enabled: true
    secretName: 'onyx-sandbox-push-secret'
    existingSecret: ""
    secretKeys:
      ONYX_SANDBOX_PUSH_SECRET: shared_secret
    values:
      shared_secret: ""   # set at deploy time
```

- Add `sandboxPush.networkPolicy.enabled: true` flag for the NetworkPolicy.
- Sandbox pods reference the same secret via a `V1EnvVarSource(secret_key_ref=V1SecretKeySelector(name="onyx-sandbox-push-secret", key="shared_secret"))` in `KubernetesSandboxManager._create_sandbox_pod`.

### Tests

```
backend/tests/unit/sandbox/
├── test_safe_extract.py        # path traversal, symlinks, special files, size caps
├── test_tarball.py             # build → extract round-trips, deterministic sha
└── test_push_orchestration.py  # SandboxManager.push_to_sandboxes default impl:
                                #   fan-out, retry on RetriableWriteError,
                                #   FatalWriteError short-circuits, result aggregation
                                #   (uses a stub SandboxManager subclass — no real backend)
backend/tests/external_dependency_unit/sandbox/
└── test_kubernetes_push.py     # KubernetesSandboxManager.write_files_to_sandbox
                                #   against a fake k8s client
backend/tests/integration/tests/sandbox/
└── test_push_e2e.py            # real sandbox via real SandboxManager; push, verify
```

## 13. Tests

### Unit (`backend/tests/unit/sandbox/`)
- Safe-extract rejects path traversal, symlinks, hard links, special files, oversized entries, writes outside `/workspace/managed/`.
- Atomic swap survives a write that fails midway (old symlink intact, new versioned dir orphaned).
- Tarball builder produces deterministic byte output given the same input (for cache-friendliness in §14).

### Orchestration unit (`backend/tests/unit/sandbox/test_push_orchestration.py`)
- `push_to_sandboxes` fans out across multiple targets, aggregates result correctly.
- `RetriableWriteError` triggers retry; `FatalWriteError` does not.
- Timeout budget exhaustion records a `timeout` failure.
- Users without active sandboxes are skipped silently.

### External-dependency unit (`backend/tests/external_dependency_unit/sandbox/`)
- `KubernetesSandboxManager.write_files_to_sandbox` produces a well-formed tar.gz with the right sha256 header.
- `LocalSandboxManager.write_files_to_sandbox` writes to the expected path and performs the atomic swap.

### Integration (`backend/tests/integration/tests/sandbox/`)
- Bring up a real sandbox, `push_to_sandbox` a small file set, verify files at the expected path inside the sandbox.
- Replace files at the same `mount_path`; confirm old files are gone (replace-as-unit semantics).
- Two parallel pushes to the same sandbox at different `mount_path`s — both succeed.

Per-feature integration tests live with each feature; the push primitive itself is what's tested here.

## 14. Future optimizations

Each can slot in behind the same caller-facing API without breaking changes.

- **Manual refresh endpoint**: `POST /api/admin/sandbox/{sandbox_id}/refresh-files` reuses the per-feature `push_to_pod` helpers to force re-hydration of a stuck sandbox. Operational safety valve for "this sandbox is behind, kick it." Cheap to add — same code path as cold-start/wakeup, just triggered on demand.
- **`If-Modified-Since` short-circuit**: per-pod last-pushed timestamp per `(pod, mount_path)`; skip unchanged pushes.
- **Celery decoupling + background retry**: if admin upload latency or the snapshot-self-heal property becomes insufficient, move per-pod fan-out and retry into a Celery task. Same API; async to the caller.
- **Redis write-through cache**: for large fan-out (tenant of 200+ users), cache materialized per-sandbox file bytes at the `push_to_sandboxes` entry point so we don't rematerialize per call.
- **Tarball-pull (daemon initiates)**: daemon pulls from an api_server endpoint instead of receiving pushes. Supports `304 Not Modified`. Same atomic-swap on the pod side.
- **Streaming for large files**: `push_to_user_stream(..., files: Iterator[tuple[str, Iterator[bytes]]])` if any future consumer needs to push beyond the 100 MiB cap. Not required for any v1 consumer.
- **Content-addressed store**: upload each unique file by SHA once; pods fetch by digest. Wins when the same bytes ship to many pods.

The archived `skills/archive/sandbox-file-sync.md` is a more elaborate scale-oriented design that anticipated several of these.

## 15. Open questions

- **Concurrent pushes to the same `mount_path`**: last-write-wins is acceptable in v1; no per-mount-path locking. If two features ever target the same path, that's the bug to fix, not the push API.
