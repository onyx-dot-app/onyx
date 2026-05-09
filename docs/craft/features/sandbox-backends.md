# Docker-Compose Sandbox Backend

## Objective

Give self-hosted Onyx a sandbox backend that's actually isolated. Today there are two backends: `local` (a directory on the host with no container boundary) and `kubernetes` (real pod isolation, but requires a K8s cluster). The middle ground is missing — a self-hosted admin who runs the standard `docker compose up` deployment has no way to run Craft sessions safely. They get `local`, which means the agent's bash tool runs as the api_server user, on the host. That's fine for a dev laptop and unacceptable for a real team.

V1 adds a third backend, `docker`, that the api_server drives directly via the Docker Engine API. One container per user, the same image family already used by Kubernetes, the same session directory layout. Self-hosted Craft becomes "set `SANDBOX_BACKEND=docker`, mount the Docker socket into the api_server, done." `local` stays as a dev-only backend; `kubernetes` stays as the cloud backend; `docker` is the production path for self-hosted.

## Issues to Address

1. **No container isolation for self-hosted users.** The agent's bash, write, and edit tools execute on the host filesystem as the api_server user. There is no syscall boundary, no resource limit, no separate UID. Anything Craft writes to `outputs/` lands on the host alongside Onyx's own data.
2. **`local` is the marketed default.** `SANDBOX_BACKEND=local` is the default in `configs.py` and the docker-compose deployment doesn't set it, so most self-hosted installs run unisolated. The current README implies "Local Mode" is suitable beyond development. It is not.
3. **Kubernetes is the only isolated path and it's heavy.** Self-hosted teams who want to run Craft are pushed to install K8s, set up IRSA, configure namespaces, and operate a sandbox node pool — which is wildly disproportionate to what they need. Docker is what they already have.
4. **Image and behavior parity.** The current `onyxdotapp/sandbox:v0.1.5` image is consumed by Kubernetes only. Self-hosted gets a different code path (process-spawned `opencode`, host filesystem, host's installed `node`, etc.). Skills, templates, and OpenCode behave differently between deployments. We've already hit at least one bug from this divergence (LibreOffice on the host doesn't match what's baked into the sandbox image).
5. **Snapshot story is inconsistent.** Kubernetes snapshots go through s5cmd-in-pod → S3. Local doesn't snapshot at all. Self-hosted Docker needs snapshots (idle cleanup, multi-replica resilience) but should reuse the existing `FileStore` abstraction so MinIO/S3/local-disk backends all work — no s5cmd.
6. **No clean abstraction for "execute command in sandbox."** K8s code uses `kubectl exec` via `k8s_stream` *everywhere* (35+ call sites). The local code uses subprocess. Adding a third backend means either copying the same surface area for Docker or pulling out a small shared `exec()` interface. We need to do enough refactoring that the third backend isn't a 2k-line copy of the second.

## Important Notes

- **`SandboxManager` is already an ABC.** `backend/onyx/server/features/build/sandbox/base.py` already defines the contract: `provision`, `terminate`, `setup_session_workspace`, `cleanup_session_workspace`, `create_snapshot`, `restore_snapshot`, `session_workspace_exists`, `health_check`, `send_message`, `list_directory`, `read_file`, `upload_file`, `delete_file`, `get_upload_stats`, `get_webapp_url`, `generate_pptx_preview`, `sync_files`, `ensure_nextjs_running`. The new backend implements that interface and gets selected via `SANDBOX_BACKEND` in `configs.py:20`. No router changes, no caller-side branching.
- **Reuse the Kubernetes sandbox image.** `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile` already produces an image with Node.js, Python venv, OpenCode CLI, LibreOffice, Poppler, the skill bundles, and the outputs template baked in. The Docker backend pulls the same image (`SANDBOX_CONTAINER_IMAGE`, currently `onyxdotapp/sandbox:v0.1.5`). Do **not** create a parallel image. Image name should be configurable; container name and label scheme should be parallel to the K8s pod name pattern (`sandbox-<first-8-chars>`).
- **Direct Docker control, not a runner service.** Settled in the main plan. The api_server uses the `docker` Python SDK to talk to the Docker Engine on the host (or a remote Docker daemon — doesn't matter, the SDK doesn't care). No new microservice.
- **`docker exec` is the K8s `kubectl exec` analogue.** The K8s manager runs every operation as `kubectl exec` into the pod — workspace setup, snapshot creation, file reads, the OpenCode ACP conversation, etc. The Docker SDK exposes `container.exec_run(...)` and `client.api.exec_create/exec_start` which give us the same thing including a stream socket for ACP. The shape of the code is parallel to K8s — there is no need to rewrite the orchestration logic, only the transport.
- **Don't bind-mount the Onyx host filesystem.** Use a Docker named volume per sandbox for `/workspace/sessions/`. Bind mounts cause UID/GID confusion across Linux/macOS/Docker Desktop and force us to chown things. Volumes are clean to create, easy to remove on terminate, and don't require knowing the host path. For knowledge files (`/workspace/files`), we expect this dir to be empty in V1 — search is moving to an HTTP tool (project #1) so the sandbox no longer needs the corpus.
- **The api_server needs the Docker socket.** Mount `/var/run/docker.sock` into the api_server container in `docker-compose.yml`, behind a clearly-documented opt-in. Self-hosted admins who don't want to mount the socket can set `SANDBOX_BACKEND=local` and accept the lack of isolation. **Mounting the socket is equivalent to root on the host** — call this out explicitly in the docs and explain that this is the same trust model that Kubernetes' RBAC for sandbox pods provides.
- **Networking.** One Docker bridge network per Craft deployment (e.g. `onyx_craft_sandbox`). The sandbox containers join it; the api_server joins it. NextJS dev servers are reachable by the api_server via the container's hostname (`sandbox-<id>:<port>`), the same way K8s reaches them via the cluster service DNS. We do **not** publish NextJS ports on the host — proxy through the api_server's existing webapp-proxy code path. This avoids host-port collisions across users, keeps the URL shape consistent with K8s (`http://<service>.<ns>.svc.cluster.local:<port>` ↔ `http://sandbox-<id>:<port>`), and keeps the sandbox off the host network.
- **Snapshots go through `FileStore`, not s5cmd.** K8s uses an s5cmd-in-pod path because the api_server can't see the pod's filesystem and IRSA is convenient. In Docker we have direct access to the container. Use the existing `SnapshotManager` (already used by `local` infrastructure-side) — exec a `tar -czf -` inside the container, stream the bytes back to the api_server, hand them to `FileStore.save_file(...)` with `FileOrigin.SANDBOX_SNAPSHOT`. Restore reverses it. This works against MinIO, S3, GCS, or local file-store backends with zero extra config.
- **Idle cleanup task.** `cleanup_idle_sandboxes_task` in `sandbox/tasks/tasks.py:50` currently checks `SANDBOX_BACKEND == LOCAL` and bails, then casts to `KubernetesSandboxManager`. Generalize this so docker mode also runs idle cleanup and snapshotting. The session-listing helper (`_list_session_directories` at `tasks.py:201`) needs a docker-aware path; ideally it moves onto the manager itself instead of being defined on K8s in the tasks module.
- **`local` retained for dev, never marketed as secure.** Update `sandbox/README.md`, `configs.py`, and the env template to make the role of each backend explicit. Default for `docker compose` deployments shifts to `docker`. Default for plain `python -m onyx.main` (running outside containers) stays `local`.
- **Backwards compat.** No migration. Per the main plan, V1 has no migration story for existing Craft sessions — they will be wiped on upgrade.
- **Don't rename the K8s docker subtree.** The Dockerfile lives at `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile`. That path is misleading once Docker (the SDK) is also a backend, but the main plan is explicit about not renaming `build/` modules in V1. Live with the awkward path; document it once in a comment.

## Approaches Considered

### A. Promote `local` to "good enough" for self-hosted (rejected)

Tighten up `LocalSandboxManager` — add chroot, drop privileges with `setuid`, restrict the python venv. Skip the Docker dependency entirely.

**Why rejected:** chroot isn't a security boundary, dropping privileges in a single Python process doesn't isolate filesystems or syscalls, and the fundamental problem is that the agent runs in the same process tree as the api_server. We'd be pretending to add isolation. The main plan says the explicit goal is *real* isolation; this approach doesn't deliver it.

### B. Bundle Kubernetes (k3s/kind/minikube) into the self-hosted distribution (rejected)

Ship a single-node K8s with the docker-compose deployment so `KubernetesSandboxManager` works everywhere.

**Why rejected:** it doubles the operational surface area for an admin whose entire deployment is otherwise five containers and a Postgres. K8s is the right answer for clustered cloud; it's the wrong answer for a 4-person self-hosted team. The whole point of having a separate backend is so docker-compose users don't pay K8s overhead.

### C. Separate "runner" microservice with an HTTP/gRPC API (rejected)

Add an `onyx-sandbox-runner` service that owns the Docker socket and exposes a JSON API. The api_server talks to the runner over HTTP. Same shape as the existing `code-interpreter` service.

**Why rejected:** the main plan settled this — direct Docker control. Concretely: a runner service means a second protocol to design, version, and version-skew across releases; a second service to deploy, monitor, restart; a second authentication boundary; and we'd still need to mount the Docker socket *somewhere*, just one container over. The argument for the runner service was "the api_server shouldn't have root-equivalent access to the host" — but in practice the api_server already does many privileged things (file ingestion, model server invocation, secret decryption) and the user-perceived security model wouldn't actually change. Skip the indirection.

### D. Direct Docker control via the Python SDK (winner)

`DockerSandboxManager` uses `docker.from_env()` (or `docker.DockerClient(base_url=...)`) to create one container per user, exec into it for workspace setup and per-message ACP, manage a docker volume for sessions, and stream snapshot tarballs back through the SDK to the existing `FileStore`.

**Why this wins:**
- **Symmetric with K8s.** `KubernetesSandboxManager` is `kubectl exec` via `k8s_stream`. `DockerSandboxManager` is `docker exec` via `client.api.exec_create/exec_start`. The orchestration code (workspace setup script, snapshot tar pipeline, file ops) is the same; only the transport changes.
- **No new service.** No new ports, no new auth, no new deployment story. Self-hosted admins gain one env var and one socket mount.
- **No new image.** Reuses `SANDBOX_CONTAINER_IMAGE`. Bug fixes to the sandbox image, new skills, or new system deps land in both backends at once.
- **Snapshots without s5cmd.** Reuses `FileStore.save_file/read_file`. Works against MinIO, S3, GCS, or local disk with no extra config. K8s can adopt this same path later (`tar | base64` through `kubectl exec`) if we want to retire the s5cmd sidecar.
- **Sets up the abstraction we already wanted.** Pulling the exec primitive out of the K8s manager into a tiny shared interface (`run_in_sandbox(container_or_pod, script) -> str`) lets future backends — Firecracker, gVisor, anything — implement only the transport.

## Key Design Decisions

1. **`SandboxBackend` gains a third value: `DOCKER = "docker"`.** Default behavior:
   - Running `docker compose up` (the supported self-hosted path): `docker`.
   - Running api_server outside any container (dev laptop): `local`.
   - Running in K8s via the helm chart: `kubernetes`.
   - The default in `configs.py` stays `local` (no behavior change for people running raw Python). The `docker-compose.yml` env block sets `SANDBOX_BACKEND=docker` explicitly.
2. **One container per user, sessions are subdirectories — same as K8s.** This keeps every callable on `SandboxManager` aligned across backends. Session lifecycle stays cheap (container survives across sessions, sessions are just directories under `/workspace/sessions/`).
3. **`docker.from_env()` from the api_server, no runner service.** The Python `docker` package becomes a backend dependency; gated to `SANDBOX_BACKEND=docker` so non-docker installs don't pull it (or, simpler, install it unconditionally — it's small).
4. **Container creation is idempotent.** Same as K8s: if a container with the expected name already exists and is healthy, reuse it. If it exists but is stopped, restart it. If it exists but is unhealthy or wedged, terminate and recreate. This protects against duplicate-provision races between API replicas (not relevant for typical self-hosted, but cheap to add and matches the K8s code path).
5. **Volumes for session state, no bind mounts.** A named docker volume per sandbox holds `/workspace/sessions/`. Removed on `terminate()`. The outputs template, skills, demo data, and venv all live inside the sandbox image — no bind mount needed. `/workspace/files` is an `emptyDir`-equivalent in V1 (search becomes HTTP) and disappears entirely once the search project lands.
6. **Networking via a private bridge network.** Create `onyx_craft_sandbox` (or similar) in the compose file. The api_server joins it; sandbox containers join it on creation. Sandbox containers are **not** published on the host — `get_webapp_url(sandbox_id, port)` returns `http://sandbox-<id>:<port>`, which the api_server reaches over the bridge. Mirrors the K8s ClusterIP path.
7. **Resource limits.** CPU and memory limits on the container match the K8s pod (1 CPU request / 2 CPU limit, 2Gi request / 10Gi limit, defaults in env). `--security-opt no-new-privileges`, `--cap-drop ALL`, `--user 1000:1000` (matching the sandbox image's user), no `--privileged`. We are not adding seccomp profiles in V1 — sandbox image already drops privileges and we have not had a use case for custom seccomp; revisit if a security review wants it.
8. **Snapshot path via `FileStore`.** `create_snapshot(sandbox_id, session_id, tenant_id)`:
   - exec `tar -czf - -C /workspace/sessions/<id> outputs attachments .opencode-data` inside the container,
   - stream the bytes back to the api_server through the SDK socket,
   - call `FileStore.save_file(content=..., file_origin=FileOrigin.SANDBOX_SNAPSHOT, file_id="<tenant>/snapshots/<session>/<snap>.tar.gz")`.
   - Returns `SnapshotResult(storage_path, size_bytes)`.
   `restore_snapshot(...)` is the inverse: download via FileStore, exec `tar -xzf - -C /workspace/sessions/<id>`. No s5cmd, no IRSA, no init container. The existing `SnapshotManager` class can be reused once the local-only assumption is loosened — see "Refactoring" below.
9. **ACP transport.** The K8s `ACPExecClient` uses `k8s_stream(... connect_get_namespaced_pod_exec ...)` and treats the resulting websocket as a JSON-RPC pipe. The Docker SDK gives `client.api.exec_create(...)` + `client.api.exec_start(detach=False, tty=False, socket=True)` which returns a duplex socket. Wrap it in a Docker analog of `ACPExecClient` (`backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py`) — same internal queue, same reader thread, same `start/stop/send_message` shape. Both clients can implement a tiny shared `ACPExecTransport` protocol if it makes the surface smaller; cosmetic, not blocking.
10. **Idle cleanup is generalized.** `cleanup_idle_sandboxes_task` no longer hard-checks `KubernetesSandboxManager`. The "list session directories in this container/pod" helper moves onto `SandboxManager` itself (`list_session_workspaces(sandbox_id) -> list[UUID]`) so the task body is backend-agnostic. The current `_list_session_directories(K8s manager)` in tasks.py is rewritten to call `manager.list_session_workspaces(sandbox_id)`.
11. **Docker socket access is documented as the trust boundary.** Self-hosted admins who don't want to mount the socket are explicitly told to keep `SANDBOX_BACKEND=local` and accept the loss of isolation. The docker-compose default assumes the admin chose `docker compose up` and is fine giving the api_server access to Docker — same trust delta as giving the api_server access to the host's filesystem already.
12. **No demo data path inside docker mode.** Per the main plan, demo data is removed alongside the legacy `files/` corpus. The K8s manager's `use_demo_data=True` symlinking code is dead in V1; the docker manager doesn't need to grow it.
13. **Refactor scope is small and bounded.** This project does not rewrite the K8s manager. It (a) extracts the per-backend differences cleanly enough that the docker manager is plausible, (b) generalizes the idle-cleanup task so it doesn't `isinstance` against K8s, and (c) loosens the file-store assumptions in `SnapshotManager` so docker can use it. Anything else stays as-is.

## Architecture

```
┌───────────────────── api_server (host or container) ─────────────────────┐
│                                                                          │
│  Craft session API                                                       │
│    │                                                                     │
│    ▼                                                                     │
│  SandboxManager (interface)                                              │
│    │                                                                     │
│    ├─ SANDBOX_BACKEND=local      → LocalSandboxManager                   │
│    ├─ SANDBOX_BACKEND=docker     → DockerSandboxManager  ◀── new         │
│    └─ SANDBOX_BACKEND=kubernetes → KubernetesSandboxManager              │
│                                                                          │
│  DockerSandboxManager:                                                   │
│    docker.from_env()                                                     │
│    container.exec_run(...)                                               │
│    client.api.exec_create/exec_start (ACP socket)                        │
│    FileStore (snapshots)                                                 │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ /var/run/docker.sock
                                   ▼
┌──────────────────── Docker Engine on the same host ──────────────────────┐
│                                                                          │
│   network: onyx_craft_sandbox (bridge)                                   │
│   ┌──────────────────────┐  ┌──────────────────────┐                     │
│   │ container            │  │ container            │   ...               │
│   │ name: sandbox-aaaa   │  │ name: sandbox-bbbb   │                     │
│   │ image: onyx/sandbox  │  │ image: onyx/sandbox  │                     │
│   │ user: 1000:1000      │  │ user: 1000:1000      │                     │
│   │ caps: drop=ALL       │  │ caps: drop=ALL       │                     │
│   │ no-new-privileges    │  │ no-new-privileges    │                     │
│   │                      │  │                      │                     │
│   │ /workspace/          │  │ /workspace/          │                     │
│   │   skills/  (image)   │  │   skills/  (image)   │                     │
│   │   templates/(image)  │  │   templates/(image)  │                     │
│   │   .venv/   (image)   │  │   .venv/   (image)   │                     │
│   │   sessions/ (volume) │  │   sessions/ (volume) │                     │
│   │   files/    (empty)  │  │   files/    (empty)  │                     │
│   └──────────┬───────────┘  └──────────┬───────────┘                     │
│              │ named volume            │ named volume                    │
│              │ onyx_sandbox_aaaa       │ onyx_sandbox_bbbb               │
└──────────────┴─────────────────────────┴─────────────────────────────────┘
```

### Per-message ACP flow

```
api_server                              sandbox container
    │                                          │
    │ docker exec_create                       │
    │   [opencode acp] --cwd sessions/<id>     │
    │                                          │
    │ docker exec_start (socket=True) ─────────► spawn opencode acp subprocess
    │                                          │   stdin/stdout = duplex socket
    │ JSON-RPC: initialize ────────────────────►
    │ ◄──────────────────── initialize result  │
    │ JSON-RPC: session/load ──────────────────►
    │ ◄──────────────────── session/load done  │
    │ JSON-RPC: session/prompt ────────────────►
    │ ◄────── stream of agent_message_chunk    │
    │ ◄────── stream of tool_call_start/...    │
    │ ◄────── prompt_response (terminal)       │
    │ exec exit ──────────────────────────────► subprocess exits; socket closes
```

## Relevant Files / Onyx Subsystems

**Selection / config (small edits):**
- `backend/onyx/server/features/build/configs.py:6` — add `DOCKER = "docker"` to `SandboxBackend`.
- `backend/onyx/server/features/build/configs.py:20` — keep default `local`; document the deployment-specific defaults in the docstring.
- `backend/onyx/server/features/build/sandbox/base.py:500` — `get_sandbox_manager()` adds the `DOCKER` branch.

**New: docker backend module:**
- `backend/onyx/server/features/build/sandbox/docker/__init__.py` — module shell.
- `backend/onyx/server/features/build/sandbox/docker/docker_sandbox_manager.py` — implements `SandboxManager`. Roughly the K8s manager's shape but ~half the line count once we drop service/IRSA/init-container code. Uses the existing `SnapshotManager` for snapshot bytes ↔ FileStore.
- `backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py` — Docker analog of `kubernetes/internal/acp_exec_client.py`. Same public surface (`start`, `resume_or_create_session`, `send_message`, `stop`, `cancel`, `health_check`); uses `client.api.exec_create/exec_start(socket=True)` instead of `k8s_stream`.
- `backend/onyx/server/features/build/sandbox/docker/internal/exec_helpers.py` — small wrapper around `container.exec_run(...)` that mirrors the `k8s_stream(... command=[...] ...)` ergonomics: returns combined stdout/stderr as a string, raises a typed error on non-zero exits, supports streaming for large outputs (snapshot tar).

**Existing files to touch:**
- `backend/onyx/server/features/build/sandbox/base.py` — add `list_session_workspaces(sandbox_id) -> list[UUID]` to the ABC. Implement it on K8s and Local (the local version walks the directory; K8s's logic moves out of `tasks.py` onto the manager). The docker version execs `ls /workspace/sessions/`.
- `backend/onyx/server/features/build/sandbox/tasks/tasks.py:67-101` — `cleanup_idle_sandboxes_task` no longer special-cases backends. Drop the `if SANDBOX_BACKEND == LOCAL: return` (replaced with: `manager.supports_idle_cleanup()` → bool, default False for local) and the `isinstance(KubernetesSandboxManager)` cast. `_list_session_directories` deleted; calls go through `manager.list_session_workspaces(...)`.
- `backend/onyx/server/features/build/sandbox/manager/snapshot_manager.py` — already takes a `FileStore` and works in tar/upload terms. Add a `create_snapshot_from_stream(stream, ...)` and `restore_snapshot_to_stream(...)` so docker can hand it raw bytes from `exec_run` rather than a path on disk. Local uses the existing path-based methods unchanged.
- `backend/onyx/server/features/build/sandbox/README.md` — section on `docker` backend, comparison table of the three backends, explicit warning that `local` is dev-only, and the trust-boundary note about the docker socket.

**Deployment / packaging:**
- `deployment/docker_compose/docker-compose.yml` — `api_server` service:
  - mount `/var/run/docker.sock:/var/run/docker.sock` (gated behind `ENABLE_CRAFT=true` via a profile or comment, depending on how the existing compose handles optionals),
  - join `onyx_craft_sandbox` network,
  - set `SANDBOX_BACKEND=docker`,
  - set `SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:<pinned>`.
  Add the `onyx_craft_sandbox` network at the top level. Same edits to `docker-compose.dev.yml` and any prod-cloud variant where Craft is expected to run.
- `deployment/docker_compose/env.template` — document `SANDBOX_BACKEND`, mention `docker` is the supported default for compose deployments and that mounting the docker socket is a privileged choice.
- `backend/requirements/default.txt` — add `docker>=7.0,<8` (Docker SDK for Python). Keep it in default; ~1 MB and harmless when unused.

**No changes needed:**
- The K8s manager — it stays. Future cleanup can move duplicated orchestration code into a shared base, but that is not in scope here.
- Existing `/api/build/...` routes. `SandboxManager` interface absorbs the new backend.
- Database models. The backend choice is config-driven, not per-sandbox-stored. (Per-sandbox `backend` column is a possible future addition if we ever want to support multiple backends in one deployment, but V1 is single-backend per install.)

## Refactoring Required

Two small refactors before the docker manager lands cleanly. Both are independently sensible — they tighten existing code regardless of whether we add a docker backend.

1. **Move "list session workspaces" onto `SandboxManager`.** Currently in `tasks.py` as a free function specialized to K8s. New abstract method:
   ```python
   @abstractmethod
   def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]: ...
   ```
   - Local: list directory entries.
   - K8s: existing `ls /workspace/sessions` exec, parsed to UUIDs, moved off the standalone function.
   - Docker: `container.exec_run("ls /workspace/sessions")`, same parser as K8s.
2. **Extend `SnapshotManager` to accept streams.** Today it takes a `Path` and reads/writes the local filesystem. Docker hands it bytes from a `docker exec` socket. Add:
   ```python
   def create_snapshot_from_stream(self, stream: BinaryIO, sandbox_id: str, tenant_id: str) -> SnapshotResult: ...
   def restore_snapshot_to_stream(self, storage_path: str) -> BinaryIO: ...
   ```
   The existing path-based methods become thin wrappers that read/write a tempfile around the stream methods.

These are the only refactors that block the docker backend. Everything else (e.g. extracting a shared base manager) can wait.

## Data Model Changes

None.

The backend is config-driven (`SANDBOX_BACKEND` env var, read once at process start). We do not store per-sandbox backend selection. If a deployment ever migrates from `kubernetes` to `docker` (or vice versa), existing `Sandbox` records become unreachable on the new backend — same as if you migrated the Kubernetes cluster. The main plan rules out a migration story in V1.

## API Changes

None at the HTTP layer. The new `list_session_workspaces` ABC method is internal.

`get_webapp_url(sandbox_id, port)` returns a different URL shape per backend, which is already true:
- Local: `http://localhost:<port>`.
- K8s: `http://<svc>.<ns>.svc.cluster.local:<port>`.
- Docker (new): `http://sandbox-<sandbox_id_8>:<port>`.

The webapp proxy in the api_server already handles whatever shape comes back. No change there.

## Tests

Lightweight. Sandbox correctness is dominated by the K8s integration tests already in place — those exercise the orchestration logic. Testing docker mode means proving the transport works and the wiring picks up the right backend. Don't re-test the workspace setup script, the AGENTS.md generation, or the OpenCode flow against three backends.

**External dependency unit (one file, the load-bearing one):**
`backend/tests/external_dependency_unit/build/sandbox/test_docker_sandbox.py`
- Spins up a real Docker daemon via the developer's local socket (skipped on CI runners that don't have Docker; mark with the existing skip pattern for daemon-required tests).
- `provision()` creates a container, idempotency check reuses an existing one.
- `setup_session_workspace()` creates `/workspace/sessions/<id>/{outputs,attachments,opencode.json,AGENTS.md}` inside the container — assert via `container.exec_run("ls ...")`.
- `create_snapshot()` produces a non-empty tarball that `restore_snapshot()` can round-trip back into a fresh session directory.
- `terminate()` removes the container and the named volume; `docker volume ls` confirms the volume is gone.
- `list_session_workspaces()` returns the UUIDs created by `setup_session_workspace()` and excludes anything that isn't a UUID-shaped directory.

**Unit (one file, only for the things that don't need a daemon):**
`backend/tests/unit/onyx/server/features/build/sandbox/test_sandbox_backend_selection.py`
- `get_sandbox_manager()` returns the right concrete class for each `SandboxBackend` value, including the new `DOCKER`.
- `SandboxBackend("docker")` parses successfully from the env value.
- Singleton caching is preserved across the three branches.

`backend/tests/unit/onyx/server/features/build/sandbox/test_snapshot_manager_streams.py`
- The new `create_snapshot_from_stream` / `restore_snapshot_to_stream` methods round-trip correctly with an in-memory `BytesIO`, against a fake `FileStore`. Confirms the tempfile-wrapping path-based API still produces the same `(snapshot_id, storage_path, size_bytes)` shape.

**Integration (no new tests):**
- The existing Craft session integration tests in `backend/tests/integration/tests/build/` (which run against `local`) should be re-run with `SANDBOX_BACKEND=docker` in a CI matrix lane *if* CI has Docker-in-Docker. If not, treat docker mode as covered by the external-dependency-unit tests plus manual verification.
- Skip Playwright. The web UI doesn't change.

**Manual smoke (do this before merging):**
- Bring up `docker compose up` with `SANDBOX_BACKEND=docker` and `ENABLE_CRAFT=true`. Mount the socket. Run a Craft session end-to-end: create a session, send a prompt, watch the agent run, view the produced artifact. Confirm the container appears under `docker ps`, the session directory under `docker exec sandbox-<id> ls /workspace/sessions/`, and the volume under `docker volume ls`.
- Idle cleanup: drop `SANDBOX_IDLE_TIMEOUT_SECONDS` to ~120s, leave a session idle, watch the Celery beat task tear down the container and snapshot the session. Restart a session on top of the snapshot, confirm `outputs/` is restored.
- Negative path: stop the Docker daemon and confirm the api_server returns a clear error rather than hanging.
- Network confinement: from inside a sandbox container, confirm direct external traffic still works in V1 (interception lands later — project #4) and confirm the api_server can reach `http://sandbox-<id>:<port>` for the NextJS preview while the host cannot (no `--publish`).

That's enough for V1. Heavier coverage — fuzz, load, multi-replica orchestration, image-update rollouts — waits until the contract stabilizes and we have real self-hosted users in this mode.
