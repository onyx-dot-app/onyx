# Onyx Craft on docker-compose - Direct Docker Backend Plan

## Context

Main goal: make Onyx Craft package cleanly for `docker compose` deployments with a containerized sandbox backend, while keeping the implementation as close as practical to the current Kubernetes Craft architecture.

Decision update: Docker authority will live in `api_server`. The api server will mount the Docker socket and use a `DockerSandboxManager` directly, analogous to how `KubernetesSandboxManager` directly talks to the Kubernetes API today.

Research checked:

- Existing `docker-compose.yml` + `install.sh` for Craft wiring:
  - `code-interpreter` already uses Docker-out-of-Docker by mounting `${DOCKER_SOCK_PATH:-/var/run/docker.sock}`.
  - docker-compose currently sets Craft template paths and `ENABLE_CRAFT`, but does not set `SANDBOX_BACKEND`; the code default is `local`.
  - `--include-craft` uses the regular image tag and sets `ENABLE_CRAFT=true`, but does not provision an isolated Craft sandbox backend.
- `KubernetesSandboxManager` (`backend/onyx/server/features/build/sandbox/kubernetes/`):
  - K8s Craft provisions one sandbox pod per user.
  - Each pod contains a `sandbox` container for the agent and a `sidecar` container for push/snapshot HTTP on port `8731`.
  - api_server talks directly to Kubernetes for lifecycle and exec, and to the sidecar for signed push/snapshot operations.

## Issues to Address

1. Docker-compose Craft currently falls back to `local`, so the agent runs inside the api_server container/process boundary.
2. Self-hosted docker-compose needs a containerized Craft backend without requiring Kubernetes.
3. The Docker backend should mirror the K8s manager shape: api_server owns sandbox lifecycle through the platform control API.
4. Craft sandboxes need per-user lifecycle, per-session workspaces, snapshot/restore, file push, ACP streaming, and Next.js preview.
5. Agent containers must not receive Docker socket access or file-store credentials.
6. EC2 IMDS exposure must be blocked or explicitly guarded. App code alone cannot safely claim this.
7. Compose install must wire the feature through `--include-craft`.

## Architecture

Direct Docker manager in api_server:

```text
api_server
  - SandboxBackend.DOCKER
  - DockerSandboxManager
  - mounts /var/run/docker.sock
  |
  | Docker Engine API
  v
sandbox-<id8>
  - image: onyxdotapp/sandbox:<tag>
  - one container per user/sandbox
  - named volume mounted at /workspace/sessions
  - no Docker socket
  - no S3/MinIO credentials
  - K8s-equivalent resource defaults for now
```

This is the closest docker-compose equivalent to Kubernetes:

```text
Kubernetes:
  api_server -> Kubernetes API -> sandbox pod

Docker compose:
  api_server -> Docker Engine API -> sandbox container
```

The initial Docker implementation should use **one sandbox container per user**, not one container per session. This matches the K8s model, where one sandbox pod contains `/workspace/sessions/<session_id>` directories for multiple sessions.

## Sidecar Decision

For Docker V1, do not require a per-sandbox sidecar unless implementation proves it is materially simpler.

Preferred V1:

```text
api_server -> Docker exec / Docker API -> sandbox container
```

Why:

- Docker exec gives api_server a direct control path for ACP, setup, file ops, snapshots, and cleanup.
- A single VM does not need the same in-pod HTTP control pattern that K8s uses to cross pod/filesystem boundaries.
- Avoids doubling the number of sandbox containers.
- Keeps Docker V1 smaller and easier to smoke test.

Keep the design compatible with adding sidecars later:

- Use labels and named volumes that could be shared with `sandbox-<id8>-sidecar`.
- Keep push/snapshot code behind manager methods, not scattered through callers.
- If Docker exec streaming becomes brittle, add an agent+sidecar pair in a follow-up.

## Compose Wiring

`api_server`:

- Mounts `${DOCKER_SOCK_PATH:-/var/run/docker.sock}:/var/run/docker.sock` when Craft is enabled.
- Sets `SANDBOX_BACKEND=docker`.
- Uses the default app-aligned sandbox image `onyxdotapp/sandbox:${IMAGE_TAG}`; `SANDBOX_CONTAINER_IMAGE` is only an internal override.
- Keeps existing Craft template envs.
- Keeps FileStore/S3/MinIO envs; snapshots are handled by api_server/FileStore, not by giving credentials to the sandbox.

`background`:

- Needs the same `SANDBOX_BACKEND=docker` config if celery tasks instantiate `get_sandbox_manager()` for idle cleanup/snapshotting.
- If background must terminate/snapshot Docker sandboxes, it also needs Docker socket access.
- Alternative: route all sandbox cleanup through api_server later, but V1 should keep parity with existing task ownership.

`code-interpreter`:

- Remains unchanged.

`install.sh`:

- `--include-craft` uses the regular image tag, sets `ENABLE_CRAFT=true`, sets `SANDBOX_BACKEND=docker`, and ensures Docker socket env guidance exists.
- It should warn clearly that api_server/background get Docker socket access, which is root-equivalent on the host.
- On EC2, either install and verify host-level IMDS blocking or fail unless `CRAFT_ALLOW_UNBLOCKED_IMDS=true` is explicitly set.

## Docker Resource Model

Keep current K8s-style sandbox expectations for now:

- one sandbox per user
- multiple session workspaces under `/workspace/sessions`
- resource defaults aligned with current K8s sandbox unless testing proves a single VM needs lower defaults

Recommended envs for future tuning, even if defaults match K8s:

- `SANDBOX_DOCKER_CPU_LIMIT`
- `SANDBOX_DOCKER_MEMORY_LIMIT`
- `SANDBOX_DOCKER_NETWORK`
- `SANDBOX_DOCKER_VOLUME_PREFIX`
- `SANDBOX_DOCKER_BLOCK_IMDS`

## Network Model

V1 should prioritize a clear separation between Onyx services and agent containers.

Recommended Docker network shape:

- Create/use a dedicated bridge network, e.g. `onyx_craft_sandbox`.
- Sandbox containers join only that network.
- api_server does not need to join that network if all control traffic uses Docker exec.
- If Next.js preview is reached by IP/port, api_server must either:
  - join the sandbox bridge network, or
  - use Docker APIs to discover the sandbox container IP and proxy from the host namespace path available inside api_server.

Important security note:

- Docker bridge networking can route to EC2 IMDS (`169.254.169.254`) unless blocked at the host or Docker daemon/network layer.
- Do not claim IMDS is fixed by application code.
- If installing host `DOCKER-USER` rules, they must cover every Docker bridge that sandbox traffic can use, and verification must run from inside an actual sandbox container.

## Snapshot and FileStore Strategy

Use api_server-owned FileStore streaming for Docker V1:

- `DockerSandboxManager.create_snapshot(...)`
  - `docker exec` runs `tar` inside the sandbox container.
  - api_server streams the tar bytes into `FileStore.save_file(...)`.
  - sandbox container never receives S3/MinIO credentials.
- `DockerSandboxManager.restore_snapshot(...)`
  - api_server reads from FileStore.
  - streams bytes into `tar -x` inside the sandbox container.

Do not use `aws s3 cp` inside the sandbox agent for Docker V1. That would require storage credentials near the untrusted workload and would only support S3-like stores.

The existing `SnapshotManager` needs stream helpers:

- `persist_snapshot_from_stream(stream, sandbox_id, tenant_id, size_hint=None)`
- `restore_snapshot_to_stream(storage_path, write_stream)`

## Implementation Strategy

### PR 1 - Shared backend refactors

- Add `SandboxBackend.DOCKER`.
- Add Docker config envs.
- Add `list_session_workspaces(sandbox_id) -> list[UUID]` to `SandboxManager`.
- Move K8s `_list_session_directories` logic out of `background/celery/tasks/build/tasks.py` and onto `KubernetesSandboxManager`.
- Add a local implementation that walks the local sandbox directory.
- Generalize `cleanup_idle_sandboxes_task` so it works for K8s and Docker; local remains cleanup-disabled.
- Add `SnapshotManager` stream helpers.

### PR 2 - DockerSandboxManager

New module:

- `backend/onyx/server/features/build/sandbox/docker/docker_sandbox_manager.py`
- `backend/onyx/server/features/build/sandbox/docker/internal/acp_exec_client.py`
- `backend/onyx/server/features/build/sandbox/docker/internal/exec_helpers.py`

Manager responsibilities:

- connect to Docker via `docker.from_env()`
- ensure sandbox network exists
- ensure sandbox named volume exists
- provision/reuse sandbox container idempotently
- labels for discovery and cleanup:
  - `onyx.app/component=craft-sandbox`
  - `onyx.app/sandbox-id=<uuid>`
  - `onyx.app/tenant-id=<tenant>`
  - `onyx.app/user-id=<uuid>`
- run container with:
  - `--security-opt no-new-privileges`
  - `--cap-drop ALL`
  - `--user 1000:1000`
  - no privileged mode
  - no Docker socket mount
  - no file-store credentials
- implement workspace setup through exec scripts, reusing K8s/local setup behavior where practical
- implement ACP using Docker exec socket transport
- implement file ops through Docker exec
- implement snapshots through tar streaming and FileStore
- implement Next.js startup and preview URL handling
- terminate container and volume cleanly

### PR 3 - Compose and install packaging

- Update `deployment/docker_compose/docker-compose.yml`:
  - add Docker socket mount to `api_server` when Craft is enabled
  - add Docker socket mount to `background` if idle cleanup runs there
  - set `SANDBOX_BACKEND=${SANDBOX_BACKEND:-docker}` when Craft is enabled
  - document the trust boundary inline
- Update `deployment/docker_compose/env.template`:
  - document `SANDBOX_BACKEND=docker`
  - document Docker socket trust boundary
  - document EC2 IMDS requirement/limitation
  - document Docker resource envs
- Update `deployment/docker_compose/install.sh`:
  - `--include-craft` writes `SANDBOX_BACKEND=docker`
  - warns that api_server/background get Docker socket access
  - handles or guards EC2 IMDS

### PR 4 - Docs and verification

- Update Craft sandbox README with the three backends:
  - `local`: dev only, no isolation
  - `kubernetes`: Helm/cloud, api_server talks to K8s
  - `docker`: docker-compose, api_server talks to Docker Engine
- Document how Docker maps to K8s:
  - K8s pod -> Docker container
  - K8s emptyDir -> Docker named volume
  - K8s exec -> Docker exec
  - K8s service/preview -> Docker network/container IP or manager proxy

## Tests

Testing is a first-class part of this project. The Docker backend should not be merged as "manual smoke only"; it needs unit coverage for selection/refactor behavior and external-dependency-unit coverage against a real Docker daemon.

### Unit tests

Target location:

- `backend/tests/unit/onyx/server/features/build/sandbox/`

Tests to add/update:

- `test_sandbox_backend_selection.py`
  - monkeypatch `SANDBOX_BACKEND=SandboxBackend.DOCKER`
  - reset the singleton manager
  - assert `get_sandbox_manager()` returns `DockerSandboxManager`
  - assert unknown backend still raises a useful error
- `test_idle_cleanup_backend_abstraction.py`
  - use a stub `SandboxManager`
  - assert `cleanup_idle_sandboxes_task` calls `list_session_workspaces()` rather than the deleted K8s-only helper
  - assert local backend still exits without cleanup
  - assert snapshot failures for one session do not prevent later sessions from being attempted
- `test_snapshot_manager_streams.py`
  - fake `FileStore`
  - `persist_snapshot_from_stream(...)` saves bytes with `FileOrigin.SANDBOX_SNAPSHOT`
  - `restore_snapshot_to_stream(...)` writes the stored bytes to the provided stream/writer
  - validates storage path, display name, metadata, and size
- `test_docker_manager_config.py`
  - unit-test naming/label/network/volume helpers without Docker
  - validate Docker resource env parsing
  - validate env allowlist excludes S3/MinIO credentials from sandbox container env
  - validate container create kwargs include `cap_drop`, `no-new-privileges`, `user=1000:1000`, memory/CPU settings, labels, and no Docker socket mount
- `test_docker_acp_exec_client.py`
  - mock Docker low-level exec socket
  - assert JSON-RPC frames can be sent/received
  - assert subprocess exit/closed socket is surfaced as a retryable or terminal error as appropriate

### External-dependency-unit tests

Target location:

- `backend/tests/external_dependency_unit/craft/test_docker_sandbox.py`
- or split by concern under `backend/tests/external_dependency_unit/craft/docker/`

Skip policy:

- Skip if Docker daemon is unavailable.
- Skip unless `SANDBOX_BACKEND=docker` or an explicit test env like `RUN_DOCKER_SANDBOX_TESTS=true` is set.
- Use unique test labels and prefixes so cleanup can remove only test-owned resources.

Required fixtures:

- Docker client fixture that verifies the daemon is reachable.
- Unique sandbox ID/user ID/tenant ID per test.
- Cleanup fixture that removes containers, volumes, and networks with test labels even after failures.
- Minimal `LLMProviderConfig` fixture.
- Fake or real FileStore fixture compatible with existing external dependency test patterns.

Lifecycle tests:

- `test_provision_creates_container_volume_and_network`
  - call `provision()`
  - assert one sandbox container exists
  - assert named volume exists and is mounted at `/workspace/sessions`
  - assert sandbox network exists and container is attached
  - assert required labels are present
- `test_provision_is_idempotent`
  - call `provision()` twice
  - assert the same container/volume are reused
  - assert stopped container is restarted rather than duplicated
- `test_terminate_removes_container_and_volume`
  - provision, then terminate
  - assert container and volume are gone
  - assert repeated terminate is safe

Workspace and file tests:

- `test_setup_session_workspace_creates_expected_layout`
  - provision and setup one session
  - exec `find /workspace/sessions/<session_id>` or use manager read/list APIs
  - assert `outputs`, `attachments`, `.opencode/skills`, `AGENTS.md`, and `opencode.json` exist
- `test_file_operations_round_trip`
  - upload file
  - list directory
  - read file
  - delete file
  - assert traversal attempts are rejected
- `test_list_session_workspaces_filters_uuid_dirs`
  - create valid and invalid directory names
  - assert only UUID session directories are returned

ACP and preview tests:

- `test_acp_exec_smoke`
  - start ACP through `DockerACPExecClient`
  - run a minimal prompt or command path that does not require external LLM if possible
  - otherwise mock only the LLM boundary while keeping Docker exec real
- `test_nextjs_preview_path`
  - setup a session with a Next.js port
  - ensure Next.js starts
  - assert manager preview URL/proxy reaches the expected HTML or health response
  - assert only configured port range is allowed

Snapshot tests:

- `test_snapshot_round_trip`
  - create files under `outputs` and `attachments`
  - call `create_snapshot()`
  - delete/recreate workspace
  - call `restore_snapshot()`
  - assert files are restored
- `test_snapshot_does_not_include_generated_runtime_state`
  - assert snapshot excludes venv, raw credentials, Docker socket mounts, and other non-user runtime state

Security/isolation tests:

- `test_sandbox_container_has_no_docker_socket_or_storage_env`
  - inspect container mounts/env
  - assert no `/var/run/docker.sock`
  - assert no `S3_AWS_ACCESS_KEY_ID`, `S3_AWS_SECRET_ACCESS_KEY`, `MINIO_ROOT_PASSWORD`, or equivalent FileStore secrets
- `test_sandbox_container_security_options`
  - inspect container config
  - assert non-root user, dropped caps, no privileged mode, no-new-privileges, expected resource limits
- `test_network_isolation_from_compose_services`
  - from inside sandbox, `curl` compose service names such as `api_server`, `relational_db`, `cache`, and `minio`
  - assert they fail when the sandbox is only on the craft network
  - assert public internet egress works if intended
- `test_imds_blocking_when_enabled`
  - only run on EC2 or when a test IMDS endpoint is configured
  - assert `169.254.169.254` is unreachable from inside the sandbox when `SANDBOX_DOCKER_BLOCK_IMDS=true`

Manual EC2 smoke:

- Fresh EC2 with Docker installed and an IAM instance profile.
- Run `curl -fsSL https://onyx.app/install_onyx.sh | bash -s -- --include-craft`.
- Verify:
  - `api_server` has Docker socket mount.
  - creating a Craft session creates one sandbox container and one named volume.
  - sandbox does not have Docker socket mount.
  - sandbox cannot reach api_server/Postgres/Redis/MinIO/model services by compose DNS if network isolation is configured.
  - sandbox can reach public internet if egress is intended.
  - sandbox cannot retrieve IMDS credentials, or install fails with the documented guard.
  - generated webapp preview loads through `/api/build/sessions/{id}/webapp`.
  - idle cleanup snapshots and terminates the sandbox, and later restore works.

## Open Decisions

1. Sidecar: omit for Docker V1, but preserve labels/volume/network structure so an agent+sidecar pair can be added later.
2. Background Docker socket: needed if celery cleanup owns Docker snapshot/termination. Confirm task ownership before wiring.
3. Preview networking: decide whether api_server joins sandbox network or proxies via Docker-discovered IP path.
4. IMDS: host-rule automation vs explicit EC2 guard. Recommendation: guard first unless host-rule automation can be deterministic and verified.

## Updated PR Sequencing

1. Shared backend refactors and stream snapshot helpers.
2. `DockerSandboxManager` and Docker external-dependency tests.
3. Compose/install/env/docs wiring under `--include-craft`.
4. EC2 smoke and security hardening pass, especially IMDS and network isolation.

## Non-Goals

- No K8s network-policy fix in this workstream.
- No migration story for existing local Craft sessions.
- No new runner service.
- No new code-interpreter changes.
- No claim of EC2 credential safety without verified IMDS blocking or an explicit install-time guard.

## Implementation Status (2026-05-20)

### What landed

| PR # | Title | Status |
| --- | --- | --- |
| #11218 (`1fce3ba78b`) | `feat(craft): backend-agnostic sandbox cleanup + snapshot stream helpers` | merged to `main` |
| `d08a5ee078` | `feat(craft): docker-compose sandbox backend` (manager + compose/install/env wiring) | open on `docker-compose-2` (#11222) |
| `d881a81a03` | `refactor(craft): simplify exec helpers and sandbox manager` | open in same stack |
| `1465bd7a61` | `chore(craft): drop CRAFT_ALLOW_UNBLOCKED_IMDS opt-out` | open in same stack |
| `e1d5bd22db` | `chore(craft): remove SANDBOX_DOCKER_BLOCK_IMDS` | open in same stack |
| `d94321e924` | `refactor(craft): shared ACPExecClient base across K8s + Docker` | open on `docker-compose-3` (#11225) — tracked separately in [`shared-acp-exec-client.md`](./shared-acp-exec-client.md) |
| `2c49919b10` | `docs(craft): document docker sandbox backend` | open on `docker-compose-2b` |

PR 3 (compose/install/env wiring) shipped inside the same PR as PR 2 (`d08a5ee078`) rather than as a separate PR. PR 4 split into the IMDS-guard simplification commits (`1465bd7a61` + `e1d5bd22db`) and the docs commit (`2c49919b10`).

### Divergences from the original plan

- **`SANDBOX_DOCKER_BLOCK_IMDS` env was removed.** The plan listed it under "Docker Resource Model" as a runtime knob. In practice an app-level Docker bridge address block is unreliable (Docker manages user-defined network routing), so the env var was removed (`e1d5bd22db`). The only IMDS defense is the host-level `DOCKER-USER` iptables rule that `install.sh --include-craft` best-effort installs on EC2.
- **`CRAFT_ALLOW_UNBLOCKED_IMDS` opt-out was dropped** (`1465bd7a61`). Install no longer hard-fails on EC2 when iptables is unavailable; it logs a clear warning with the manual command and continues. This matches the plan's "Open Decision 4 — Recommendation: guard first" but lands the guard as best-effort rather than blocking.
- **Per-container resource defaults match K8s pod requests, not limits.** Plan said "match K8s sandbox unless testing proves a single VM needs lower defaults." Actual defaults are `1 CPU / 2 GiB`, matching K8s requests (not the K8s `2 CPU / 10 GiB` limits), because single-VM compose deployments cannot over-commit every sandbox.
- **Background does mount the Docker socket** (Open Decision 2 resolved → yes). The idle-cleanup celery task owns snapshot+terminate, so `background` gets the same socket mount and `onyx_craft_sandbox` network attachment as `api_server`.
- **api_server joins the sandbox bridge network** (Open Decision 3 resolved → joins, not proxies via discovered IP). Both `api_server` and `background` attach to `default` plus `onyx_craft_sandbox`, so the Next.js preview reaches sandboxes by container DNS / IP on the bridge.
- **Sidecar still omitted** (Open Decision 1 resolved as planned). Docker V1 ships agent-only; labels and the named volume are structured so a sidecar can be added later without disturbing the layout.
- **`SANDBOX_API_SERVER_URL` is required to be the *public* HTTPS URL**, not a compose hostname — documented in `env.template` and `sandbox/README.md`. The agent cannot resolve `api_server` by DNS from inside the sandbox bridge.
- **Tests:** the external-dependency-unit Docker tests outlined in the plan landed alongside the manager. The plan-mode unit tests for `test_sandbox_backend_selection.py` / `test_idle_cleanup_backend_abstraction.py` / `test_snapshot_manager_streams.py` / `test_docker_manager_config.py` / `test_docker_acp_exec_client.py` were implemented as part of PR #11218 and `d08a5ee078`.

### Still TODO

- Manual EC2 smoke test on a fresh EC2 + IAM-role instance — verifying IMDS block, sandbox→compose-service unreachability, and snapshot/restore round-trip on real infra. The plan's `## Tests → Manual EC2 smoke` block remains the checklist.
- Cherry-pick + merge of the `docker-compose-2` and `docker-compose-3` PR stack.
