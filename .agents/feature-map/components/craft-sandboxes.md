# Craft Sandboxes

> The container a Craft session runs in: provisioning, the pod spec, the exec
> sidecar, the shared workspace volume, snapshot and restore, and reaping.
> This document does not cover session/turn orchestration, streaming, the
> webapp preview, or admin policy; it covers the runtime the agent executes
> inside.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE (Craft ships in both editions; no EE-specific code in this path)
**Owns:**
`backend/onyx/server/features/build/sandbox/base.py`, `factory.py`, `models.py`,
`labels.py`, `session_workspace.py`, `snapshot_manager.py`, `serve_transport.py`,
`event_schema.py`, `nextjs_dev.py` (spec only; the runtime lives in
`[[craft-webapp-proxy]]`),
`backend/onyx/server/features/build/sandbox/kubernetes/` (`kubernetes_sandbox_manager.py`,
`k8s_client.py`, `sidecar_client.py`),
`backend/onyx/server/features/build/sandbox/docker/` (`docker_sandbox_manager.py`,
`dev_mode_serve.py`, `internal/exec_helpers.py`),
`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/` (`server.py`,
`snapshot.py`, `extract.py`, `filesystem.py`, `outputs_manifest.py`, `models.py`,
`opencode_history.py`),
`backend/onyx/server/features/build/sandbox/util/` (`agent_instructions.py`,
`opencode_config.py`, `mcp_config.py`, `api_url_check.py`),
`backend/onyx/server/features/build/db/sandbox.py`,
`backend/onyx/server/features/build/session/sandbox_lifecycle.py`,
`backend/onyx/background/celery/tasks/build/tasks.py`,
`deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`, `sandbox-rbac.yaml`,
`network-policy-sandbox-egress.yaml`, `network-policy-sandbox-push.yaml`

**Read first:** `docs/craft/sandbox/image-and-spinup.md` for the image and cold-start
story, and `docs/craft/infra/snapshot-retention.md` for the retention policy. Several
`docs/craft/` files under this domain describe **plans, not current behaviour** (see
§9); this document states what the code does today and flags each discrepancy.

---

## 1. What the user experiences

Every user who has Craft enabled gets exactly one sandbox: a container (pod or
Docker container, depending on deployment) that runs their agent sessions. The
user never provisions it explicitly; it is created on first use and reused across
sessions (`backend/onyx/server/features/build/sandbox/base.py:SandboxManager`,
class docstring, "User-Shared Sandbox Model"). Each Craft session gets its own
directory inside that shared sandbox, not its own container.

If the user is idle for an hour (`SANDBOX_IDLE_TIMEOUT_SECONDS`, default 3600,
`backend/onyx/server/features/build/configs.py:29`), the sandbox is put to sleep:
its container is destroyed, but each session's generated files and chat history
are captured first so the next message wakes a fresh container and restores them.
The user experiences this as a short delay ("waking up") on their next message
after a long gap, not as lost work, unless a snapshot could not be taken (see §4.4
and §9).

---

## 2. Surfaces

Craft sandboxes have no direct HTTP surface for end users; they are driven
internally by `[[craft-sessions]]` and `[[craft-streaming]]`. The externally
visible seams:

- `POST /api/build/sessions/{session_id}/snapshot` and
  `POST /api/build/sessions/{session_id}/opencode-history-snapshot`
  (`backend/onyx/server/features/build/session/api.py:create_session_snapshot`, `create_session_opencode_history_snapshot`): manual snapshot
  triggers for the owned session. The history one is a manual capture hook used
  by tests and operators (`backend/tests/integration/common_utils/managers/build_session.py:BuildSessionManager.create_opencode_history_snapshot`). No frontend code calls it.
- The sandbox's own preview/dev-server surface is owned by `[[craft-webapp-proxy]]`.

### Environment configuration (`backend/onyx/server/features/build/configs.py` unless noted)

| Variable | Default | Effect |
|---|---|---|
| `SANDBOX_BACKEND` | `kubernetes` | `kubernetes` or `docker`; picked by `factory.py:get_sandbox_manager`. There is no `local` backend. |
| `SANDBOX_IDLE_TIMEOUT_SECONDS` | 3600 | Idle threshold the reaper (`sandbox_lifecycle.py:is_sandbox_idle`) checks. |
| `SANDBOX_NAMESPACE` | `onyx-sandboxes` | K8s namespace sandbox pods/services live in. |
| `SANDBOX_CONTAINER_IMAGE` | `onyxdotapp/sandbox:latest` | Overrides the chart's normal image default; see `docs/craft/infra/image-architecture.md`. |
| `SANDBOX_SERVICE_ACCOUNT_NAME` | `sandbox` | Service account the pod runs as; must match `deployment/helm/charts/onyx/templates/sandbox-rbac.yaml`. |
| `SANDBOX_NEXTJS_PORT_START` / `_END` | 3010 / 3100 | Per-session Next.js dev-server port range, shared by the Service, the NetworkPolicy, and the PodTemplate's container ports. |
| `ONYX_SANDBOX_PUSH_PRIVATE_KEY` | required | Ed25519 seed signing every sidecar request (`kubernetes/sidecar_client.py:get_push_key_pair`). |
| `SANDBOX_PROXY_HOST` / `SANDBOX_PROXY_NAMESPACE` | required (K8s) / `onyx` | The egress-proxy endpoint pinned via `hostAliases` (see §5, §9). |
| `SANDBOX_LISTEN_HOST` | `0.0.0.0` | Shared listener for OpenCode, the sidecar, and generated previews. Helm `sandboxPod.listenHost` sets it; use `::` for IPv6-only pods. |

Celery task: `CLEANUP_IDLE_SANDBOXES` (`backend/onyx/background/celery/tasks/build/tasks.py`),
scheduled every `SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS` on self-hosted beats
(`beat_schedule.py:get_tasks_to_schedule`). In `MULTI_TENANT` deployments,
`get_cloud_tasks_to_schedule` fans the same template out with the cloud beat
multiplier (`backend/onyx/background/celery/tasks/beat_schedule.py`). The default
interval is `SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS * 8`
(`CLOUD_BEAT_MULTIPLIER_DEFAULT`). Operators can change the multiplier in Redis
(`backend/onyx/server/runtime/onyx_runtime.py:OnyxRuntime.get_beat_multiplier`). It is consumed by the
**`sandbox` Celery queue**, currently routed to `celery-worker-heavy`
(`docs/craft/infra/sandbox-worker-network-policy.md`).

---

## 3. Data model

- `Sandbox` (`backend/onyx/db/models.py:Sandbox`): one row per user
  (`user_id` unique). Carries `status: SandboxStatus`
  (`PROVISIONING`/`RUNNING`/`SLEEPING`/`TERMINATED`/`FAILED`,
  `backend/onyx/db/enums.py:SandboxStatus`), `last_heartbeat`, `provisioning_attempt_number`
  (fencing token for concurrent provisioners, see §4.1), `skills_hash` and
  `mcp_config_hash` (last-pushed managed-content fingerprints), and
  `encrypted_pat` (the Craft-scoped PAT injected into the sandbox).
- `Snapshot` (`backend/onyx/db/models.py:Snapshot`): one row per **session** output
  snapshot, `storage_path` + `size_bytes`, FK to `BuildSession`. Only one row is
  kept per session (`get_latest_snapshot_for_session`,
  `backend/onyx/server/features/build/db/sandbox.py`); see §4.4 for
  prune-on-write.
- Labels (`backend/onyx/server/features/build/sandbox/labels.py`):
  `LABEL_SANDBOX_ID` / `LABEL_TENANT_ID` (stamped onto the K8s Pod/Service, and
  used as the Docker manager's equivalent tag), `LABEL_PROVISIONING_ATTEMPT`
  (operator-facing only, never read programmatically), `LABEL_K8S_COMPONENT`
  (`"sandbox"`, the NetworkPolicy pod selector).
- Snapshot storage layout (FileStore, `FileOrigin.SANDBOX_SNAPSHOT`,
  `backend/onyx/server/features/build/sandbox/snapshot_manager.py`):
  - Session snapshot: `sandbox-snapshots/{tenant_id}/{sandbox_id}/{snapshot_id}.tar.gz`
    (`persist_snapshot_from_stream`), a fresh UUID-named blob each write.
  - Sandbox-global opencode history: a **fixed** path,
    `sandbox-snapshots/{tenant_id}/{sandbox_id}/opencode-history.tar.gz`
    (`SnapshotManager.opencode_history_storage_path`), overwritten in place each
    capture rather than versioned.

---

## 4. How it works

### 4.1 Two managers, one interface

`SandboxManager` (`base.py`) is an `ABC` defining the full lifecycle contract:
`provision`, `terminate`, `setup_session_workspace`, `cleanup_session_workspace`,
`create_snapshot`/`restore_snapshot`, `session_workspace_exists`,
`list_session_workspaces`, `health_check`, `send_message` (turn streaming, see
`[[craft-streaming]]`), and filesystem primitives (`list_directory`, `read_file`,
`upload_file`, `delete_file`, `write_sandbox_file`). It explicitly forbids talking
to the database directly (`base.py`, module docstring): every caller (session
lifecycle code, Celery tasks) owns its own DB transactions.

`factory.py:get_sandbox_manager` picks the implementation from `SANDBOX_BACKEND`
and caches a process-wide singleton, assigned only after construction succeeds so
a failed init retries on the next call (`factory.py:20-57`):

- **`KubernetesSandboxManager`** (`kubernetes/kubernetes_sandbox_manager.py`): the
  production backend. One Kubernetes Pod per user, with true container/pod
  isolation, a sidecar container, RBAC-scoped API access, and FileStore-backed
  snapshots streamed through the sidecar.
- **`DockerSandboxManager`** (`docker/docker_sandbox_manager.py`): the
  self-hosted docker-compose backend. One Docker container per user on a
  dedicated bridge network, snapshots streamed through `docker exec` instead of
  a sidecar HTTP API. There is **no sidecar container** on Docker; filesystem
  and snapshot operations exec directly into the sandbox container
  (`docker_sandbox_manager.py`, module docstring, "Snapshots"). The manager
  reads the bridge's `EnableIPv4` flag. IPv6-only bridges inject
  `SANDBOX_LISTEN_HOST=::`; IPv4 and dual-stack bridges retain `0.0.0.0`.
  Proxy listener configuration is separate: use `SANDBOX_PROXY_LISTEN_HOST=::`
  for an IPv6-only bridge, with complete internal CIDRs. The API can remain
  on the original Compose network because the proxy forwards sandbox API
  traffic. Existing IPv4 bridge behavior remains the default.

Where they diverge, by design (`docker_sandbox_manager.py` module docstring,
"Threat model: Docker vs Kubernetes parity gap"):
- K8s isolates via the pod/network boundary plus an iptables lockdown inside the
  container; Docker additionally cap-drops the container itself
  (`--cap-drop ALL`, `--security-opt no-new-privileges`, `user=1000:1000`, no
  Docker-socket mount, no S3/Postgres/Redis credentials in env,
  `docker_sandbox_manager.py:536-561`).
- K8s snapshot I/O goes through the always-running sidecar's signed HTTP API;
  Docker's `create_snapshot`/`restore_snapshot` run `tar` via `docker exec` and
  pipe bytes through the same `SnapshotManager` (`docker_sandbox_manager.py`
  module docstring, "Snapshots").
- Both managers set `supports_opencode_history_persistence = True` (the base
  class defaults it `False`, `base.py`). On Docker, `_maybe_restore_opencode_history`
  restores the archive before the sandbox serves, with no sidecar
  `startupProbe` gate. A new backend must set the flag itself.
- Only the dedicated sandbox bridge network is used on Docker; Postgres, Redis,
  MinIO, and the model server stay unreachable by service name
  (`docker_sandbox_manager.py` module docstring, "Security model").

### 4.2 Provisioning (Kubernetes)

`ensure_sandbox_ready` (`session/sandbox_lifecycle.py:690`) drives a
reserve → reconcile → finalize state machine, split so no DB transaction spans
external I/O (module docstring):

1. **Reserve** (`reserve_sandbox__no_commit`, short transaction, user row
   locked): create or find the `Sandbox` row, assign a new
   `provisioning_attempt_number` (a fencing token: every later status write is
   conditional on the row still holding that number,
   `db/sandbox.py:finalize_provisioning_attempt__no_commit`), and mint/reuse the
   Craft PAT (`db/sandbox.py:ensure_sandbox_pat`).
2. **Reconcile** (`reconcile_sandbox`, no open transaction):
   - If already `RUNNING`, a cheap `health_check` against the pod confirms it is
     real; an unhealthy `RUNNING` row triggers **recovery** (snapshot opencode
     history best-effort, terminate, re-provision under a new attempt number).
   - `KubernetesSandboxManager.provision` (`kubernetes_sandbox_manager.py:996`)
     is idempotent: if a healthy pod already exists it is reused. Otherwise it:
     a. Provisions a per-pod opencode-serve auth Secret
        (`_provision_opencode_secret`).
     b. Reads the Helm **PodTemplate** named `sandbox-pod` and overlays the
        dynamic fields (see §4.3) to build the `V1Pod`
        (`_create_sandbox_pod`, `_overlay_dynamic_fields`).
     c. Creates the Pod, then the ClusterIP Service
        (`_ensure_service_exists`, handles a Terminating leftover Service).
     d. Waits for a pod IP, then calls
        `restore_opencode_history_snapshot` **before** the main container's
        readiness gate opens (the init sidecar serves the restore endpoint while
        its own `startupProbe` blocks, so opencode-serve never opens an empty DB
        first, `provision()` step 3 comment).
     e. Watches for pod `Ready` (`_wait_for_pod_ready`, uses
        `kubernetes.watch.Watch()`, not polling; see §5, §9 for the RBAC this
        requires) and for opencode-serve to bind its port.
   - Managed content (skills, user library, MCP fingerprint) is pushed
     best-effort (`push_managed_content`) before the sandbox is reported
     `RUNNING`, because turns can dispatch the instant `RUNNING` is visible.
3. **Finalize** (short transaction): `finalize_provisioning_attempt__no_commit`
   records `RUNNING`/`FAILED`, a no-op if a newer attempt superseded this one.

A per-sandbox Redis lock (`_provisioning_lock`,
`kubernetes_sandbox_manager.py:195`) serializes pod creation across api-server
replicas; a losing acquirer raises `SandboxProvisionContentionError`, which the
lifecycle layer treats as retryable.

`setup_session_workspace` (per-session, called after `provision`) execs into the
pod (`k8s_stream`/`connect_get_namespaced_pod_exec`) to run a replay-safe,
`flock`-serialized shell script (`session_workspace.py:build_session_workspace_setup_script`)
that creates `/workspace/sessions/$id/{outputs,attachments}`, symlinks `.opencode/skills` and
`user_library` to the sandbox-wide managed directories, writes `AGENTS.md` and
`opencode.json`, and (if the session has a port) writes `start-webapp.sh`. It
never scaffolds or starts the dev server itself (`[[craft-webapp-proxy]]` owns that).
New session config directories copy the image's preinstalled OpenCode plugin SDK
from `/workspace/templates/opencode`. Existing dependencies and package manifests
remain intact. Older images without this template use OpenCode's install fallback.
The image-owned script handles SDK copies
(`backend/onyx/server/features/build/sandbox/image/seed-opencode-dependencies.sh`).
Configuration regeneration also calls this script after snapshot restore.
A session seed lock serializes copies. Dependencies publish by rename after copying.
Kubernetes verifies a completion sentinel before reporting configuration regeneration success.
SDK files stay outside snapshots, which contain outputs and attachments.
Global configuration directories hardlink template dependencies to save image space.
Their manifests and all session dependency copies remain independent.
A completion sentinel (`ONYX_WORKSPACE_SETUP_COMPLETE`) is the only reliable
success signal, because the K8s exec client returns buffered output without
raising on a nonzero exit or timeout (`session_workspace.py` module docstring).

### 4.3 The pod: Helm PodTemplate, sidecar, shared volume

```
                     Pod "sandbox-{uuid[:8]}"  (namespace onyx-sandboxes)
 ┌─────────────────────────────────────────────────────────────────────┐
 │ initContainer: sandbox-init   (NET_ADMIN, firewall-init.sh)         │
 │   installs the proxy CA, applies the iptables egress lockdown        │
 │                                                                       │
 │ initContainer (restartable, restartPolicy=Always): sidecar           │
 │   /workspace/sidecar-entrypoint.sh -> sandbox_daemon/server.py :8731 │
 │   mounts: workspace, opencode-data, managed, sidecar-tmp, ca-bundle  │
 │   readinessProbe /health, startupProbe /ready (blocks on             │
 │   opencode_history_restored())                                      │
 │                                                                       │
 │ container: sandbox                                                   │
 │   /workspace/entrypoint.sh -> opencode-serve :4096, per-session      │
 │   Next.js dev servers on 3010-3099                                   │
 │   mounts: workspace (rw), opencode-data (rw), managed (ro), tmp,     │
 │   ca-bundle (ro)                                                     │
 │                                                                       │
 │ volumes (all emptyDir, pod-lifetime only):                           │
 │   workspace (50Gi)  -> mounted at /workspace/sessions in BOTH        │
 │                        sandbox and sidecar containers                │
 │   opencode-data (5Gi) -> /workspace/opencode-data in both            │
 │   managed (5Gi)     -> /workspace/managed (rw sidecar, ro sandbox)   │
 └─────────────────────────────────────────────────────────────────────┘
```
(`deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`)

**The pod spec comes from a Helm-rendered `core/v1` `PodTemplate` object**, not
from Python. `KubernetesSandboxManager._create_sandbox_pod`
(`kubernetes_sandbox_manager.py`) calls
`read_namespaced_pod_template(name="sandbox-pod", namespace=SANDBOX_NAMESPACE)`,
deep-copies `.template.spec`, and overlays only a few dynamic fields
(`_overlay_dynamic_fields`):
`spec.host_aliases` (the resolved proxy ClusterIP; DNS is blocked by the
firewall so the pod can't resolve it itself), the two `secretKeyRef` env entries
on the sandbox container (the per-pod opencode-auth Secret name), the sandbox
container's `ONYX_WEBAPP_ALLOWED_DEV_ORIGINS` env value (from
`allowed_dev_origins()`), the sidecar's push public key env var, and (separately, at pod-creation time) the object's
name and `LABEL_SANDBOX_ID`/`LABEL_TENANT_ID`/`LABEL_PROVISIONING_ATTEMPT`
labels. Everything else, including the container images, resource
requests/limits, security contexts, node selector/tolerations, volumes, and
probes, is defined once in
`deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml` and instantiated
per user at runtime. A missing PodTemplate is a hard provisioning failure with a
named error (`_create_sandbox_pod`, 404 branch), and `_require_container` raises
a clear "PodTemplate/api-server version skew" error rather than a bare
`StopIteration` if an expected container is absent.

**This means changing the sandbox image, resource limits, node placement, or
volumes is a Helm change, not a Python change.** `docs/craft/sandbox/sandbox-podtemplate.md`
reads as a forward-looking design proposal ("Goal: move the static shape of the
sandbox Pod into a Helm-rendered PodTemplate...") but **this has already
shipped**: the template file and the `read_namespaced_pod_template` call both
exist in the current tree. Treat that doc as historical rationale.

**The exec sidecar** (`_SIDECAR_CONTAINER_NAME = "sidecar"`) is a K8s
"restartable init container" (`restartPolicy: Always` on an `initContainers`
entry): it starts before the main container, keeps running for the pod's whole
life, and can be restarted independently by the kubelet without restarting the
main container. It runs `sandbox_daemon/server.py`
(`image/sandbox_daemon/server.py`), a FastAPI app on port 8731
(`PUSH_DAEMON_PORT`, `models.py`) that owns nearly all filesystem access:
`/push` (file bundle install), `/filesystem/list`, `/filesystem/outputs-manifest`,
`/snapshot/create`, `/snapshot/restore/{session_id}`,
`/opencode-history/{create,restore,mark-restored}`, `/health`, `/ready`. Every
mutating endpoint verifies an Ed25519 signature over
`{timestamp}|{path}|{sha256}` (`server.py:_verify_signature`), keyed against
`ONYX_SANDBOX_PUSH_PUBLIC_KEY`, the public half of the api-server's
`SANDBOX_PUSH_PRIVATE_KEY` (`kubernetes/sidecar_client.py:get_push_key_pair`).
The main container and the sidecar **share state only through the three mounted
volumes** (`workspace` at `/workspace/sessions`, `opencode-data` at
`/workspace/opencode-data`, and `managed` at `/workspace/managed`, read-write in
the sidecar and read-only in the sandbox); there is no other IPC (`shareProcessNamespace:
false`), which is exactly why the Next.js dev-server process itself must stay a
`kubectl exec` into the main container rather than move to the sidecar
(`docs/craft/sandbox/sandbox-exec-sidecar.md`, "Residual exec is exactly the
Next.js dev-server lifecycle").

`kubernetes/sidecar_client.py:SidecarClient` is what the api-server talks to:
signed `GET`/`POST` over plain HTTP to
`http://{pod-name}.{namespace}.svc.cluster.local:8731`, with retry-until-deadline
on transient failures (`_post`) and a streaming path for archive
create/download (`request_and_stream_new_snapshot`).

Directory listings use one `FilesystemEntry` model in `sandbox_daemon/models.py`
across the daemon, both sandbox managers, and the API. The sidecar client returns
these validated entries directly.

The outputs manifest scans visible regular files under `outputs/` without reading file contents.
It shares file browsing's hidden-name rules through `sandbox_daemon/models.py`.
The scan excludes dotfiles, dependencies, caches, runtime logs, symlinks, and special files.
It also skips the root web subtree within outputs before descent. Nested directories named `web` remain visible.
All examined entries count toward one scan budget, including ignored names and directories.
A depth limit bounds recursion. Descriptor-relative descent refuses symlinks at every workspace component.

Kubernetes sends a signed request with the session ID. Docker invokes
`python -E -s -m sandbox_daemon.outputs_manifest` from the root-owned `/opt` copy.
Both transports call `build_outputs_manifest` and return paths, sizes, modification times, change times, and completeness.
The API exposes sizes and string revisions, so JavaScript does not round nanosecond timestamps.
Revisions include change time to detect same-size overwrites that preserve modification time.
Missing session workspaces, scan limits, and unreadable entries make the response incomplete.
An existing workspace without an outputs directory returns a complete empty response.
Callers must not infer deletions from incomplete responses.

This contract requires the matching sandbox image alongside the API server.
Existing healthy sandboxes keep their image until replacement.
Update running sandboxes through the normal snapshot and recovery lifecycle during rollout.

**Current state versus the sidecar-migration doc:** as of this code, snapshot
create/restore and file push already go through the sidecar HTTP API (confirmed
above). `list_directory` and `get_outputs_manifest` also use the sidecar.
`setup_session_workspace`, `cleanup_session_workspace`,
`session_workspace_exists`, `list_session_workspaces`, `read_file`,
`upload_file`, `delete_file`, `write_sandbox_file`, `get_upload_stats`, and
`regenerate_session_config` still use
`k8s_stream`/`connect_get_namespaced_pod_exec` shell scripts today.
`docs/craft/sandbox/sandbox-exec-sidecar.md` is a **plan** to move those
remaining filesystem operations onto the sidecar too, leaving `kubectl exec`
only for the Next.js dev-server process-control call sites. Do not assume
that migration is complete; verify against the manager methods you're touching.

### 4.4 The workspace volume

`workspace` is a K8s `emptyDir` (`sizeLimit: 50Gi`,
`sandbox-podtemplate.yaml`), mounted at **`/workspace/sessions`** in both the
`sandbox` and `sidecar` containers (`SESSIONS_ROOT`, both
`session_workspace.py:19` on the api-server side and
`image/sandbox_daemon/snapshot.py:18` inside the image, kept as two literal
copies because the daemon can't import the api-server package at runtime,
per `base.py:62-67`'s comment). Session directories live directly under it:
`/workspace/sessions/$session_id/{outputs,attachments,venv,.opencode/skills,AGENTS.md,
start-webapp.sh}` (`kubernetes_sandbox_manager.py` builds `{SESSIONS_ROOT}/{session_id}`;
`base.py` class docstring, "Directory Structure", shows the generic layout). `emptyDir`
means this volume, and everything in it, **is destroyed with the pod**; nothing
here survives a `terminate()` unless captured into a snapshot first (§4.5).

`opencode-data` (`sizeLimit: 5Gi`) is a **separate** `emptyDir`, mounted at
`/workspace/opencode-data` in both containers, holding opencode's own SQLite
history database (`opencode/opencode.db`). It is **not** part of a session's
`outputs`/`attachments` tree and is captured by a **different, sandbox-wide**
snapshot mechanism (§4.5); `docs/craft/infra/snapshot-retention.md`'s claim that
the per-session snapshot includes `.opencode-data/` does not match the code
(`base.py:create_snapshot` docstring and `image/sandbox_daemon/snapshot.py`'s
own "Sandbox-global opencode history lives outside the session tree and is
snapshotted separately" comment both say otherwise). Treat the retention doc's
wording there as imprecise.

`managed` (`sizeLimit: 5Gi`) holds pushed skills and the user library, mounted
read-write in the sidecar and read-only in the sandbox container; sessions
symlink into it rather than copying (`session_workspace.py`).

### 4.5 Snapshot and restore

**What triggers a snapshot** (`session/sandbox_lifecycle.py`,
`background/celery/tasks/build/tasks.py:cleanup_idle_sandboxes_task`):

1. **Idle reap** (`sleep_sandbox`, `sandbox_lifecycle.py:810`): when a sandbox
   has had no heartbeat for `SANDBOX_IDLE_TIMEOUT_SECONDS` (default 1h), the
   sweep snapshots the sandbox-global opencode history, then every session's
   outputs/attachments, **before** terminating the pod. This path is
   **fail-closed**: a session-output snapshot failure on a reachable pod aborts
   the reap (sandbox stays `RUNNING`, retried next sweep); only an unreachable
   pod is terminated anyway, because its workspace is already unrecoverable.
2. **Periodic background snapshot** (same task, non-idle branch): the sweep
   skips a sandbox unless its user has a stale ACTIVE session
   (`db/sandbox.py:user_has_stale_active_session`). Otherwise, workspaces whose
   latest `Snapshot` is older than
   `SANDBOX_IDLE_TIMEOUT_SECONDS / 4` (15 min at the default) get re-snapshotted
   even though the sandbox stays `RUNNING`, bounding data loss from an
   *ungraceful* pod death (node eviction, spot reclaim, crash) rather than a
   clean reap. The sandbox-global opencode history is re-captured in the same
   sweep **only if at least one session's output snapshot actually succeeded**
   (`tasks.py`: `if snapshots_created and ...supports_opencode_history_persistence`).
3. **Recovery** (`snapshot_opencode_history_before_recovery`,
   `sandbox_lifecycle.py:151`): best-effort opencode-history capture right
   before an unhealthy `RUNNING` sandbox is terminated for re-provisioning.
4. **Manual API** (`POST /{session_id}/snapshot`,
   `POST /{session_id}/opencode-history-snapshot`, §2): the history endpoint
   is a manual capture hook for tests and operators. No frontend code calls it.

**What a session snapshot contains:** the session's `outputs/` and
`attachments/` directories only (`base.py:create_snapshot` docstring); `venv`,
skills, `AGENTS.md`, and the `user_library` symlink are excluded and regenerated
on restore. `node_modules` and `.next` are excluded even from `outputs/`
(`image/sandbox_daemon/snapshot.py:_SNAPSHOT_GENERATED_DIR_NAMES`), rebuilt on
restore via `bun install` against a pre-warmed Bun cache
(`docs/craft/sandbox/image-and-spinup.md`, "Snapshot daemon path quick reference").

**How it's taken (Kubernetes):** the api-server POSTs to the sidecar's
`/snapshot/create` (`SnapshotCreateRequest{session_id}`); the sidecar
(`image/sandbox_daemon/snapshot.py`) tars the session's `outputs`/`attachments`
in-process and streams the archive back over the open HTTP response; the
api-server pipes that stream straight into FileStore
(`SnapshotManager.persist_snapshot_from_stream`) without ever writing it to the
pod's disk on the api-server side. A `204` means nothing to snapshot.

**How restore works:** `KubernetesSandboxManager.restore_snapshot`
(`kubernetes_sandbox_manager.py`) reads the archive back out of FileStore,
streams it to the sidecar's `/snapshot/restore/{session_id}` with a SHA-256
integrity header, the sidecar extracts it under a temp dir and atomically
swaps it into place (`sandbox_daemon/extract.py:safe_extract_then_atomic_swap`,
symlink-swap plus a delayed `rmtree` of the old target), then
`regenerate_session_config` rewrites `AGENTS.md`/`opencode.json` (not part of
the snapshot) and, if the session has a port, the webapp bootstrap script is
rewritten and the dev server is restarted via exec, but only if the restored
snapshot actually contains a webapp.

**Retention: prune-on-write, keep one in the normal case.** After a new session snapshot
lands, `create_session_snapshot_keep_latest`
(`session/sandbox_lifecycle.py:174`) deletes every prior `Snapshot` for that
session (`SnapshotManager.delete_snapshot`, idempotent: a missing blob counts as
already-deleted). The new archive is stored before any old blob is deleted.
Pruning is best-effort. If `delete_snapshot` raises, the function logs a
warning and keeps that old row, so more than one `Snapshot` row can remain.
The new `Snapshot` row is committed only after those deletions
(`db_session.commit()` is the last step). A commit failure in that window can
leave no restorable snapshot, because the old blobs are already gone.
The sandbox-global opencode history snapshot is **not** versioned at all: it
overwrites one fixed FileStore path each capture (§3).

**Opencode-history durability, stated plainly:** opencode session/chat history
lives in `/workspace/opencode-data`, an `emptyDir` destroyed with the pod. It is
durable only from the moment it is captured into the sandbox-global snapshot
described above. The capture points are: idle reap (always), periodic
background snapshot (only when a session output snapshot also succeeded that
tick, roughly every 15 minutes of active use at defaults), and best-effort
recovery. **There is no per-turn capture.** Work that lives only in opencode's
history (not in a session's `outputs/`) since the last successful capture is
lost if the pod dies ungracefully (node eviction, OOM-kill, spot reclaim,
crash) between captures.

### 4.6 Reaping

Reap = `sleep_sandbox` (§4.5, step 1), run from `cleanup_idle_sandboxes_task`.
Idle is `last_heartbeat` (falling back to `created_at`) older than
`SANDBOX_IDLE_TIMEOUT_SECONDS` (`sandbox_lifecycle.py:is_sandbox_idle`). On
reap: snapshot opencode history, snapshot every session's outputs, re-check
idleness (snapshotting can take minutes), terminate the pod+service
(`KubernetesSandboxManager.terminate`), mark the `Sandbox` row `SLEEPING`
(conditional on the attempt number that started the reap, so a concurrent
wake wins cleanly), clear allocated Next.js ports, and mark the user's
`BuildSession` rows `IDLE`. A session creation lock is held around the
existence check and the final kill so a session cannot be created mid-reap and
then have its brand-new workspace deleted. The next request for that user
re-provisions from `SLEEPING` (§4.2) and restores each session on demand.

---

## 5. Contracts and invariants

1. **A session's workspace must be recoverable or explicitly declared lost.**
   The reap path is fail-closed for reachable pods (snapshot failure keeps the
   sandbox `RUNNING` for retry); only an unreachable pod is terminated without
   a fresh snapshot, and that is a deliberate, logged exception, not silent
   data loss (`sandbox_lifecycle.py:sleep_sandbox`).
2. **A snapshot write must not corrupt the previous one.** New-blob-before-delete:
   the new blob is stored before any prior blob is deleted, but the DB commit is
   the last step (`create_session_snapshot_keep_latest`, §4.5). A commit failure
   after the prunes can leave no restorable snapshot. Restore extracts
   to a temp dir and atomically renames into place
   (`sandbox_daemon/extract.py:safe_extract_then_atomic_swap`).
3. **The pod spec lives in Helm, not in Python.** `_create_sandbox_pod` reads
   the `sandbox-pod` PodTemplate and overlays only the dynamic fields
   Python owns (§4.3). A change to resources, images, volumes, or security context belongs
   in `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`; adding
   it in Python instead will be silently overwritten by the next
   `read_namespaced_pod_template` call or, worse, drift from what the chart
   documents.
4. **The sandbox must not reach internal cluster/host addresses.** Enforced at
   two layers: the in-pod iptables lockdown
   (`image/firewall-init.sh:step_apply_iptables`, applied by the `sandbox-init`
   init container, dropping all outbound traffic except to the proxy) is
   authoritative; the `onyx-sandbox-egress`
   NetworkPolicy (`network-policy-sandbox-egress.yaml`) is a CNI-layer
   backstop that only takes effect where the cluster's CNI enforces
   NetworkPolicy, and allows only the proxy and DNS. See §9 and `[[craft-admin]]`
   §5.4 for why this is a different mechanism from the egress-proxy action
   gate. Both IPv4 and IPv6 OUTPUT chains use a DROP policy. They allow
   loopback and established connections. Only the resolved proxy address
   family permits new TCP connections to the proxy port. IPv6 permits
   neighbor solicitations and advertisements with hop limit 255. The unused
   address family stays blocked, including IPv4 compatibility egress on EKS.
5. **The sidecar and main container must agree on the workspace path.**
   `SESSIONS_ROOT` is defined twice (`session_workspace.py:19` on the
   api-server side, `image/sandbox_daemon/snapshot.py:18` inside the image)
   because the daemon cannot import the api-server package at runtime
   (`backend/onyx/server/features/build/configs.py`). A path change on one side without the other silently
   breaks snapshot/restore or workspace setup.
6. **Every sidecar-mutating request must be Ed25519-signed and fresh.**
   `_verify_signature` (`sandbox_daemon/server.py`) checks both the signature
   and a 60-second timestamp drift window; an unsigned or stale request is
   rejected with 401, never executed.
7. **`SandboxManager` implementations must not touch the database.** Stated
   in `base.py`'s module docstring; all DB writes belong to the caller
   (`session/sandbox_lifecycle.py`, the Celery task). A manager method that
   grows a DB read/write breaks this separation and the "no transaction spans
   external I/O" invariant `ensure_sandbox_ready` depends on.
8. **A provisioning attempt's writes are fenced by `provisioning_attempt_number`.**
   Every status-changing UPDATE in `db/sandbox.py` is conditional on the row
   still holding the attempt's number; a superseded attempt's late writes are
   guaranteed no-ops, never a stale overwrite of a newer attempt's outcome.
9. **`supports_opencode_history_persistence` must be checked before calling
   the opencode-history methods.** The base class implementation raises
   `NotImplementedError` (`base.py:create_opencode_history_snapshot`); `KubernetesSandboxManager` and
   `DockerSandboxManager` set the flag `True`.

---

## 6. Relationships

**Depends on**
- [[craft-admin]]: `util/agent_instructions.py:generate_agent_instructions` reads
  `Settings.craft_instructions` (via `load_settings()`) and splices the
  "Organization instructions" section into every session's `AGENTS.md`
  (`kubernetes_sandbox_manager.py:_load_agent_instructions`); the network-egress
  model described here is a different mechanism from the action-policy gate
  `[[craft-admin]]` §5 owns.
- [[multi-tenancy]]: every sandbox, snapshot path, and cache lock is
  tenant-scoped (`tenant_id` threaded through `provision`, `create_snapshot`,
  the provisioning lock key).
- [[background-jobs]]: the reap/background-snapshot sweep is a Celery beat
  task (`CLEANUP_IDLE_SANDBOXES`); scheduled-task wakeups
  (`ensure_sandbox_running`) go through the same reserve/reconcile/finalize
  machinery headlessly.
- [[file-store-and-user-files]]: every snapshot blob is a FileStore object
  under `FileOrigin.SANDBOX_SNAPSHOT`.

**Depended on by**
- [[craft-sessions]]: session create/restore calls
  `setup_session_workspace`/`restore_snapshot` directly; a session cannot exist
  without a `RUNNING` sandbox.
- [[craft-streaming]]: `SandboxManager.send_message` (via `_ServeMixin` /
  `serve_transport.py`) is the transport a turn's tokens and tool calls stream
  over.
- [[craft-webapp-proxy]]: previews a session's Next.js dev server, which runs
  inside this sandbox on a port this component allocates and exposes via the
  ClusterIP Service; `nextjs_dev.py`'s bootstrap-script *content* is owned here,
  its runtime lifecycle is owned there.
- [[craft-external-apps]]: the egress proxy this component's iptables lockdown
  routes traffic to is where connected-app credential injection and action
  policy actually run; see `[[craft-admin]]` for the policy surface.
- [[code-execution]]: contrast only. The chat code interpreter's isolation
  (`[[code-execution]]` §4.1) is an unverified infrastructure assumption
  delegated to an external service this codebase has no code for. Craft
  sandboxes are the opposite: a fully-owned, in-repo mechanism (Helm PodTemplate,
  RBAC, NetworkPolicy, a purpose-built signed sidecar daemon, FileStore-backed
  snapshot/restore) with its isolation, network posture, and persistence model
  all implemented and testable in this tree.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes the sandbox image (`image/Dockerfile`, `initial-requirements.txt`) | the app-image/sandbox-image tag coupling (`docs/craft/infra/image-architecture.md`); the prepuller DaemonSet's pinned tag (`sandbox-image-prepuller.yaml`); `ENABLE_SKILLS` build-arg gating; re-run the spinup benchmark (`kubernetes/scripts/bench-sandbox-spinup.sh`) |
| changes the pod template (`sandbox-podtemplate.yaml`) | `_overlay_dynamic_fields`/`_require_container` (version-skew handling); the dynamic fields Python still owns; resource requests vs the CI/localdev values overlays; the Service's port range staying in sync with the template's container ports |
| changes the snapshot format (what's included/excluded, archive layout) | `sandbox_daemon/snapshot.py`'s `_SNAPSHOT_ROOTS`/`_SNAPSHOT_GENERATED_*` sets; `restore_snapshot`'s webapp-restore path; existing snapshots in FileStore become unreadable by a format change unless restore stays backward-compatible |
| changes the sidecar contract (`models.py`, `server.py` routes) | both `sidecar_client.py` (api-server side) and every route in `sandbox_daemon/server.py`; the image must ship the updated daemon in the same release as the api-server that calls it (version skew is a real risk, no negotiation exists) |
| changes RBAC (`sandbox-rbac.yaml`) | `_wait_for_pod_ready`'s `watch.Watch()` usage needs `pods:watch`; removing it makes every provision fail with an `ApiException`, and no unit test catches it (see §9); `pods/exec` is still needed for the many residual exec call sites; `_create_sandbox_pod`'s `podtemplates:get` |
| changes network policy (`network-policy-sandbox-*.yaml`) | the in-pod iptables lockdown (`firewall-init.sh`) stays authoritative regardless of CNI enforcement; keep the allow-list in sync with whichever worker consumes the `sandbox` Celery queue (currently `celery-worker-heavy`) |
| changes idle timeout or snapshot cadence | the `SNAPSHOT_INTERVAL_DIVISOR` relationship between idle timeout and background-snapshot freshness bound; opencode-history durability exposure scales with this gap |
| adds a new sandbox-wide (not per-session) persisted artifact | it needs its own capture point like opencode history's, since only `outputs/`+`attachments/` ride the per-session snapshot |

---

## 8. How to verify a change

### Tests

```bash
# Unit: daemon logic, manager plumbing, config generation
cd backend && uv run pytest tests/unit/onyx/server/features/craft/sandbox
cd backend && uv run pytest tests/unit/onyx/server/features/craft/sandbox/sandbox_daemon

# External dependency unit: lifecycle, PAT, image prepuller chart render
cd backend && uv run pytest tests/external_dependency_unit/craft/test_sandbox_lifecycle.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_ensure_sandbox_running.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_sandbox_pat.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_terminated_sandbox_fast_fail.py
cd backend && uv run pytest tests/external_dependency_unit/craft_helm/test_sandbox_image_prepuller.py

# Integration: real kind cluster / real docker-compose sandboxes
cd backend && uv run pytest tests/integration/tests/craft/k8s/test_kubernetes_sandbox.py
cd backend && uv run pytest tests/integration/tests/craft/k8s/test_kubernetes_sandbox_file_ops.py
cd backend && uv run pytest tests/integration/tests/craft/docker_e2e/test_sandbox_network_posture_docker.py
```

See `docs/craft/dev/local-kubernetes.md` for standing up the kind cluster these
integration tests need, and `docs/craft/dev/local-compose-craft.md` for the
docker-compose backend. See `backend/AGENTS.md` for authoritative env/command
details.

**RBAC gaps only appear when exercised live.** A missing `pods:watch`
permission does not fail at import time or in a unit test with a mocked
client; it only surfaces as a real `ApiException` from `_wait_for_pod_ready`'s
`watch.Watch()` call against a live (or kind) API server. `helm template`
lint checks the Role renders; it does not check the Role is sufficient. Only
`test_kubernetes_sandbox.py` against a real cluster exercises the actual verb
set.

### Manual reproduction

1. Confirm services are up; for K8s, `kubectl -n onyx-sandboxes get pods`.
2. Start a Craft session, send a message, confirm a `sandbox-{id}` pod appears
   `Running`/`Ready` with `sandbox` + `sidecar` containers.
3. Force an idle reap: lower `SANDBOX_IDLE_TIMEOUT_SECONDS` or wait it out,
   confirm the pod is deleted and the `Sandbox` row moves to `SLEEPING`
   (`psql` per root `CLAUDE.md`'s connection snippet).
4. Send a new message to the same session; confirm the pod is recreated and
   the session's prior outputs are present (restore worked).
5. Delete the sandbox's `sandbox-pod` PodTemplate and attempt to provision a
   new sandbox; confirm a clear "PodTemplate not found" error, not a hang.

### What "working" looks like

- Idle reap always snapshots before terminating a reachable pod; a reachable
  pod whose snapshot fails stays `RUNNING`, never goes dark silently.
- A restored session's `outputs/` matches what was there before sleep, minus
  `node_modules`/`.next` (rebuilt).
- The pod never carries S3/Postgres/Redis credentials or a Docker socket
  (Docker backend) or reaches cluster-internal service names other than the
  proxy alias (K8s backend).

---

## 9. Footguns

- **The pod spec is Helm-owned; don't add fields in Python.** Anything beyond
  the dynamic fields `_overlay_dynamic_fields` sets belongs in
  `sandbox-podtemplate.yaml`. `docs/craft/sandbox/sandbox-podtemplate.md` reads
  like an open plan but the migration it describes is **already done** in this
  tree; don't redo it or "restore" the old field-by-field Python construction.
- **`pods:watch` is an easy-to-miss RBAC trap.** `_wait_for_pod_ready` uses
  `kubernetes.watch.Watch()` (`kubernetes_sandbox_manager.py`), which needs
  the `watch` verb on `pods` in `sandbox-rbac.yaml`. Nothing in the Python
  code names the verb explicitly (it calls `list_namespaced_pod` through the
  watch wrapper), so `grep`-ing the manager for RBAC requirements will miss
  it; the RBAC template's own comment ("watch is required: `_wait_for_pod_ready`
  streams pod events during provision") is the only place this is spelled out.
  A trimmed-down Role that looks unused-but-safe makes every provision fail:
  `_wait_for_pod_ready` re-raises the authorization `ApiException` from the
  watch request. There is no polling fallback.
- **Opencode-history durability is snapshot-dependent, and the only automatic
  capture points are idle reap and a ~15-minute-cadence background sweep
  (itself gated on a session output snapshot also succeeding that tick).**
  There is no per-turn capture. An ungraceful pod death between captures loses
  whatever opencode-only history (not reflected in a session's `outputs/`)
  accumulated since the last one. See §4.5.
- **`docs/craft/infra/snapshot-retention.md` overstates what the per-session
  snapshot captures.** It says the snapshot includes `.opencode-data/`; the code
  (`base.py:create_snapshot`, `sandbox_daemon/snapshot.py`) says opencode data is
  a separate, sandbox-wide artifact captured by a different code path. Don't
  trust that doc's exact scope claim; trust `_SNAPSHOT_ROOTS` and the manager
  docstrings.
- **`docs/craft/sandbox/sandbox-exec-sidecar.md` is also a plan, partially
  done.** Snapshot/push are already on the sidecar; workspace setup/cleanup/
  existence/listing are still `kubectl exec`. Check the manager method's actual
  implementation, not the doc, before assuming a filesystem op goes through
  the signed HTTP path.
- **General internet egress from a sandbox is allowed by design; only
  connected-app traffic is policy-gated.** The iptables lockdown
  (`firewall-init.sh`) drops all outbound traffic except to the proxy, which
  forwards public HTTPS (needed for `npm`/`pip`); the NetworkPolicy is a CNI-dependent backstop
  restricted to the proxy and DNS only, which is stricter-looking but inert on
  non-enforcing clusters. Neither of these is the same control as the
  egress-proxy's action-policy gate (`[[craft-admin]]` §5.4), which only
  evaluates traffic attributed to a connected app or MCP server. Don't conflate
  "the sandbox can reach `example.com`" with "the org didn't approve that."
- **Docker has no sidecar.** Anything in this document keyed on "the sidecar"
  is Kubernetes-only; the Docker backend execs directly into the single
  sandbox container for the same operations. It does support opencode history
  persistence (`supports_opencode_history_persistence = True`), through
  `docker exec` instead of the sidecar.
- **`emptyDir` volumes vanish with the pod, full stop.** `workspace` and
  `opencode-data` are not persistent volumes; anything not captured by a
  snapshot before `terminate()` is gone, including on a crash the reaper never
  gets to run for.
- **The sandbox-global opencode-history snapshot is a single overwritten
  blob, not versioned like session snapshots.** A corrupted or short write to
  it (rare, but the sidecar's SQLite backup step exists specifically to avoid
  copying a hot, inconsistent DB file) has no fallback prior version to
  restore from the way a session's outputs/attachments do.

### Document thumbnail conversion

Both providers use `SandboxManager.generate_document_preview` for PowerPoint slides
and first-page PDF or PowerPoint thumbnails. They deploy the shared converter and
LibreOffice helper as real files in a versioned bundle through the existing sandbox
push API. This bundle is independent of enabled agent skills.

The converter checks session workspace confinement. The 20 MiB thumbnail size
check is advisory preflight. Concurrent edits can change input during rendering.
A 30-second thumbnail deadline and 120-second full-slide deadline bound lock waiting
and conversion time. The lock opens without blocking and must be a regular file.

Finished JPEGs replace cached files atomically. Failed conversion retains the last
complete image. Source revision checks reject changed input; cache metadata records
the rendered revision. Missing, invalid, or non-regular metadata causes regeneration. Metadata opens do not block on special files or follow symlinks.
Both providers validate conversion status and session-relative JPEG paths with one parser.

Thumbnails live under `outputs/.document-thumbnails`, which inventory rules hide.
Both providers exclude this root cache from snapshots. Nested user directories
with the same name remain in snapshots.
