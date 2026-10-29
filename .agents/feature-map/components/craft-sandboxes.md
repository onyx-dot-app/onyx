# Craft Sandboxes

> The sandbox a user's Craft sessions run in, on Kubernetes or Docker:
> provisioning, the sidecar daemon, snapshot and restore, idle sleep, resource
> cleanup, and the network lockdown that sends all traffic to the egress proxy.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE

---

## User experience

Each Craft user has one sandbox, created on first use and shared by all of
that user's sessions. Each session has its own session workspace, a directory
inside the sandbox. The user never manages the sandbox.

After an idle period (`SANDBOX_IDLE_TIMEOUT_SECONDS`, one hour by default) the
sandbox sleeps: the platform saves each session's outputs, attachments and the
agent's chat history, then removes the container. The next message wakes a new
container and restores the session, with a short delay. Work that only lives
outside `outputs/` and `attachments/`, such as installed packages or browser
logins, is not kept.

The agent can reach the public internet through the egress proxy to install
packages and read docs. It cannot reach cluster or host services other than
the Onyx API and Craft MCP servers that the proxy allows.

An operator deploys sandboxes on Kubernetes (the default) or Docker Compose.
When the pod template, RBAC or network setup is wrong, provisioning fails and
the user sees Craft fail to start.

In this document "session workspace" is the directory of one session under
`/workspace/sessions`. "Workspace" alone, as in "workspace policy", means the
tenant-wide scope and belongs to [[craft-admin]].

---

## Scope

This component owns:
- the sandbox manager interface and its Kubernetes and Docker backends;
- the sandbox image, the in-pod sidecar daemon and the network lockdown;
- the sandbox lifecycle: provisioning, health, sleep and wake, and the Craft
  PAT the sandbox uses;
- session snapshots, the opencode history archive, and the cleanup of runtime
  resources;
- the Helm sandbox pod template, RBAC and network policies, and the local
  Kubernetes dev tooling.

Neighbours:
- [[craft-sessions]]: sessions, turns and `SessionManager`, which call this
  component.
- [[craft-external-apps]]: the egress proxy, its CA and action policies.
- [[craft-webapp-proxy]]: running and previewing the Next.js dev server.
- [[craft-admin]]: organization instructions, which this component renders
  into each session's agent instructions file.

---

## Architecture

Operator guides: `backend/onyx/server/features/build/sandbox/README.md` (image
and tag coupling, IPv6), `backend/onyx/server/features/build/sandbox/docker/README.md`
(Docker backend), and `deployment/helm/dev/README.md` (local kind cluster).

```
SessionManager / scheduled executor / sweep
  -> session/sandbox_lifecycle.py:ensure_sandbox_ready
       reserve   (short txn, user row locked) a new provisioning_attempt_number
                 when it must provision; Craft PAT
       reconcile (no txn) health check; provision() reuses a healthy pod or
                 creates one from the PodTemplate; restore opencode history
                 before the main container is ready; push managed content
       finalize  (short txn) RUNNING or FAILED, only if the attempt still owns
                 the row
  -> SandboxManager.setup_session_workspace (per session)

Pod "sandbox-<id>" (namespace onyx-sandboxes)
  init: sandbox-init       firewall-init.sh: install proxy CA, iptables lockdown
  init (restartable): sidecar  sandbox_daemon/server.py, signed HTTP API:
                           push, list, outputs manifest, snapshot, history
  container: sandbox       opencode serve, per-session Next.js dev servers
  volumes (emptyDir): workspace /workspace/sessions, opencode-data, managed
```

**One interface, two backends.** `backend/onyx/server/features/build/sandbox/base.py:SandboxManager` defines the
lifecycle, and callers own every transaction ([[#managers-never-touch-db]]). On
Kubernetes the API server talks to the sidecar over signed HTTP
(`backend/onyx/server/features/build/sandbox/kubernetes/sidecar_client.py:SidecarClient`) and uses `kubectl exec`
for the rest. Docker has no sidecar; it runs the same work with `docker exec`
in the single container.

**The pod spec comes from Helm.** `KubernetesSandboxManager._create_sandbox_pod`
reads the `sandbox-pod` PodTemplate and `_overlay_dynamic_fields` adds only
per-pod values: a `hostAliases` entry for the proxy (DNS is blocked inside the
pod), the per-pod opencode Secret references, the dev-origin allowlist, and
the sidecar's push public key. Images, resources, volumes, probes and security
context live in `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`.
A PodTemplate is used because pods are created per user at run time.

**Network lockdown.** `backend/onyx/server/features/build/sandbox/image/firewall-init.sh` sets IPv4 and IPv6
OUTPUT policy to DROP and allows only loopback, established connections, TCP
to the proxy, and the ICMPv6 types that IPv6 neighbour discovery needs. The
`deployment/helm/charts/onyx/templates/network-policy-sandbox-egress.yaml` policy is a second layer where the CNI
enforces it. With `sandboxPod.netAdminLockdown: false`, the init container
skips iptables, and the cluster must enforce proxy-only egress before the
workload starts. Docker always applies the lockdown. A change to these
settings reaches new pods only; running pods keep their lockdown.

**Snapshots.** A session snapshot holds `outputs/` and `attachments/` only.
The agent instructions file, the opencode config, skills and the venv are
rebuilt on restore. The opencode chat history in `opencode-data` is a separate
sandbox-wide archive at one fixed FileStore path, overwritten on each capture.
Capture points:
- sleep (`backend/onyx/server/features/build/session/sandbox_lifecycle.py:sleep_sandbox`): history, then every session;
- the periodic sweep: sessions whose last snapshot is older than
  `SANDBOX_IDLE_TIMEOUT_SECONDS / SNAPSHOT_INTERVAL_DIVISOR`
  (`background/celery/tasks/build/tasks.py`), for users with a
  stale active session, then history only if a session snapshot succeeded;
- recovery of an unhealthy pod (`snapshot_opencode_history_before_recovery`);
- cleanup of a failed runtime (`backend/onyx/server/features/build/session/resource_cleanup.py:_checkpoint_failed_runtime`).

History restore runs before the main container starts, so `opencode serve`
cannot open an empty database first. The sidecar is a restartable init
container whose startup probe hits `/ready`, and `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/server.py`
fails `/ready` until the history is marked restored
(`KubernetesSandboxManager.provision` restores it, then calls
`_mark_opencode_history_restored`). Keep this gate for any sandbox-wide state
that boot must restore.

`create_session_snapshot_keep_latest` commits the new snapshot row before it
deletes old ones. On Kubernetes, restore extracts to a staging directory and
then replaces `outputs/` and `attachments/`
(`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/snapshot.py:restore_snapshot`). The Docker backend extracts
in place with `tar`. Managed-content pushes, not snapshots, use
`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/extract.py:safe_extract_then_atomic_swap`.

**Sweep.** `cleanup_idle_sandboxes_task` runs on the `sandbox` Celery queue.
It first reconciles runtime resources
(`backend/onyx/server/features/build/session/resource_cleanup.py:reconcile_sandbox_resources`): it fails stale
`PROVISIONING` attempts and deletes runtime resources
(`backend/onyx/server/features/build/sandbox/models.py:SandboxResourceKind`) whose owner row is absent, failed,
sleeping or terminated, after a grace period. It then snapshots active
sandboxes and puts idle ones to sleep. Sleep also clears every Next.js port of
the user, so a restored session can get a different port
([[craft-webapp-proxy]]).

**Managed content.** Provisioning and a live push build the skills and user
library payload with the same code
(`backend/onyx/server/features/build/session/sandbox_lifecycle.py:build_managed_content_payload`). The read transaction
must close before the push. `push_managed_content` runs before the sandbox is
reported `RUNNING`, because opencode scans the skills directory once per
instance: a turn that starts during the push misses managed skills for good. It
logs a failure and never raises. `skills_hash` is written
only after a successful push, so the next session create or reload retries.
User library blobs use `FileOrigin.USER_FILE` but have no `UserFile` rows, so
the chat user-file lifecycle does not apply to them.

**Document previews.** `SandboxManager.generate_document_preview` converts a
PDF or PowerPoint file in the session workspace to page images inside the
sandbox. LibreOffice and poppler ship in the image only when it is built with
`ENABLE_SKILLS=true`, the default
(`server/features/build/sandbox/image/Dockerfile`). [[craft-sessions]]
calls it for deck slides and for first-page output thumbnails. The page images
are cached under `outputs/.pptx-preview` and `outputs/.document-thumbnails`,
keyed by a hash of the source path, and reused while the source revision
matches.

**LLM credentials.** The opencode gateway config holds a placeholder API key
(`backend/onyx/server/features/build/session/llm_config.py:build_onyx_gateway_config`). The egress proxy
overwrites the auth headers for the API host with the Craft PAT.

**The Craft PAT.** `server/features/build/db/sandbox.py:ensure_sandbox_pat`
mints one `PatType.CRAFT` token per user, with only the `CRAFT_SANDBOX` scope
and a 30-day expiry, and stores it encrypted on `Sandbox.encrypted_pat`. It
reuses the stored token only when it is the user's single active Craft PAT
with the current scopes. Otherwise it revokes the user's other Craft PATs and
mints a new one. The reserve step calls it on each provision. For a healthy
sandbox it re-mints only when `has_active_craft_pat` is false, for example
after a password change revoked it ([[auth-and-identity]]). The proxy reads
the stored token on each request, so a new token takes effect at once.

---

## Contracts and traps

1. `image-ships-with-api-server` **The API server and the sandbox image ship
   together; running pods keep their image.** The image tag follows the
   application tag. The sidecar daemon ships in the image and the API server
   calls it, with no version negotiation. A healthy pod is reused, so an old
   image stays in use until sleep or recovery replaces the pod. Change both
   sides of a sidecar or `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/models.py` contract in one release,
   and make new requests safe against an old daemon. Stored archives cross
   deploys too: a sleeping session wakes from a session archive or history
   archive that older code wrote. A change to the archive layout or
   `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/snapshot.py:_SNAPSHOT_ROOTS` must keep `restore_snapshot`
   and the history restore able to read the old form, or sleeping sessions
   lose outputs or agent history.
2. `internet-egress-intentional` **General internet egress is intentional.**
   The lockdown forces traffic to the proxy, and the proxy forwards public
   hosts with no policy check. Only requests to a connected app or MCP server
   are policy-gated ([[craft-external-apps]]). Do not treat "the sandbox
   reached `example.com`" as a bypass. Do not add an allowlist without a
   product decision: package installs depend on it.
3. `pod-fields-in-helm` **Put pod fields in Helm, not Python.** A field set in
   Python outside
   `server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:KubernetesSandboxManager._overlay_dynamic_fields` drifts from the chart.
   `_require_container` raises a version-skew error when the template lacks an
   expected container.
4. `pods-watch-rbac` **`pods:watch` is required.**
   `server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:KubernetesSandboxManager._wait_for_pod_ready` uses
   `kubernetes.watch.Watch()`. Python never names the verb, so a search for
   RBAC needs misses it. Without it, provisioning fails whenever the pod is not
   ready at the first read, with no polling fallback. Only a real cluster test
   shows this.
5. `provisioning-writes-fenced` **Provisioning writes are fenced.** Status
   updates in `server/features/build/db/sandbox.py` require the row to still
   hold the attempt's `provisioning_attempt_number`. A superseded attempt's
   late write does nothing. Keep this condition on every new status write.
6. `sleep-fail-closed` **Sleep is fail-closed.** If any snapshot or session
   workspace listing fails,
   `server/features/build/session/sandbox_lifecycle.py:sleep_sandbox` aborts and the sandbox stays
   `RUNNING` for the next sweep. An unhealthy endpoint does not prove files are
   lost. The session creation lock is held around the final check and
   termination, so a new session cannot start in a pod that is being removed.
7. `exec-completion-sentinel` **Use the completion sentinel for exec
   scripts.** The Kubernetes exec client returns buffered output without
   raising on a non-zero exit or a timeout. Session workspace setup is done
   only when the output holds the sentinel from `backend/onyx/server/features/build/sandbox/session_workspace.py`.
8. `sessions-root-defined-twice` **`SESSIONS_ROOT` is defined twice.**
   `backend/onyx/server/features/build/sandbox/session_workspace.py` and `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/snapshot.py`
   each hold it, because the daemon cannot import the API server package.
   Change both.
9. `sidecar-requests-signed` **Sidecar requests are signed and fresh.**
   `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/server.py:_verify_signature` checks an Ed25519 signature
   over timestamp, path and body hash, with a 60-second window. The worker that
   runs the `sandbox` queue needs the push private key and the sidecar-port
   ingress rule in `deployment/helm/charts/onyx/templates/network-policy-sandbox-push.yaml`. The `scheduled_tasks`
   worker drives sandboxes too, so the same policy also gives it the opencode
   and dev-server ports. Update the policy if either worker or queue moves.
10. `history-persistence-flag` **Check `supports_opencode_history_persistence`
    first.** The base class
    `server/features/build/sandbox/base.py:SandboxManager.create_opencode_history_snapshot` raises
    `NotImplementedError`. A new backend must set the flag, implement it, and
    restore the history during provisioning.
11. `cleanup-proof-not-cache` **Do not mix cleanup proof with cache state.**
    Before it deletes the resources of a `FAILED` sandbox, cleanup takes a
    fresh checkpoint unless `Sandbox.cleanup_checkpoint` still matches the
    attempt, storage identity and heartbeat
    (`backend/onyx/server/features/build/session/resource_cleanup.py:_prepare_failed_resource_cleanup`). It deletes with
    the observed resource identity. The Redis retry key only delays a retry; a
    cache entry never authorizes a deletion. A heartbeat clears the proof
    (`server/features/build/db/sandbox.py:update_sandbox_heartbeat`, which
    flushes; a function of the same name in
    `server/features/build/db/build_session.py` commits), so any path that writes
    into a session workspace must commit a heartbeat before the write, as
    `SessionManager.upload_file` and `delete_file` do. Without it, a sweep can
    delete a volume or pod that holds files no checkpoint captured.
12. `preview-cache-dot-prefix` **Preview caches depend on the dot prefix.** The
    caches live under `outputs/`, so only the leading dot keeps them out of the
    output list (`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/models.py:is_hidden_workspace_name`).
    Snapshots exclude `outputs/.document-thumbnails` in two places that must
    agree: `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/snapshot.py:_is_excluded_snapshot_dir` and the
    `tar --exclude` in `DockerSandboxManager`. A new cache under `outputs/`
    needs a dot name and, if it must not survive sleep, an entry in both
    places.
13. `managers-never-touch-db` **Sandbox managers never touch the database.**
    Implementations of `backend/onyx/server/features/build/sandbox/base.py:SandboxManager` take no session. The
    caller (`SessionManager`, Celery tasks) owns every transaction. Managers
    make one database read: `load_settings()` for the organization instructions
    when they build the agent instructions file ([[craft-admin]]). Callers
    avoid a transaction across pod or container I/O, with one exception:
    `SessionManager.upload_file` holds the session row lock through the file
    write, to enforce the attachment quota ([[craft-sessions]]).

---

## Decisions

- **One sandbox per user, not per session.** Sessions share a warm pod, the
  managed skills and the user library.
- **A signed sidecar for file and snapshot work.** The main container never
  holds object-store credentials; the API server stores archives through the
  FileStore. Do not add storage CLIs to the image.

---

## Known issues

- Opencode history has no per-turn capture. A pod that dies between capture
  points loses the chat history recorded since the last one. The history
  archive has no older version to fall back to.
- The backends snapshot different content. The Kubernetes daemon excludes
  `node_modules` and `.next` and fails above 100 MiB
  (`backend/onyx/server/features/build/sandbox/image/sandbox_daemon/snapshot.py:MAX_SNAPSHOT_ARCHIVE_BYTES`). The Docker
  manager's `tar` excludes only the thumbnail cache and has no size limit.
  Neither backend excludes `outputs/.pptx-preview`, so slide images count
  toward the Kubernetes limit. Because sleep is fail-closed, a Kubernetes
  session above the limit can keep its sandbox awake. These consequences are
  reasoned from the code, not tested.
- Agent browser state lives outside the session workspace and is lost on
  sleep. Saving it would put login cookies in FileStore snapshots.
- Docker mode mounts the host Docker socket in the API server and background
  worker. Only enable it on hosts you control (see the sandbox `README.md`).

---

## Dependencies

- [[craft-external-apps]]: the proxy all sandbox traffic goes through; its CA
  is installed by `backend/onyx/server/features/build/sandbox/image/firewall-init.sh`.
- [[craft-admin]]: organization instructions in the agent instructions file.
- [[file-store-and-user-files]]: snapshot archives under
  `FileOrigin.SANDBOX_SNAPSHOT`.
- [[background-jobs]]: the Beat entry and the `sandbox` queue.
- [[multi-tenancy]]: tenant labels on resources and tenant keys in paths and
  locks.
- [[skills]]: managed skill content pushed into the `managed` volume.
- [[auth-and-identity]]: the PAT type and its revocation on password change.

---

## Recipes

- `sidecar-endpoint` **A sidecar endpoint.** Copy the snapshot-create route in
  `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/server.py` and its `SidecarClient` call; list the routes
  with `git grep -n '@app\.' backend/onyx/server/features/build/sandbox/image/sandbox_daemon/server.py`.
  Keep the signature check, and add the models to `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/models.py`.
  Handle an old daemon that lacks the route ([[#image-ships-with-api-server]]).
  Give the Docker backend the same behaviour with `docker exec`.
- `sandbox-wide-artifact` **A sandbox-wide artifact that must survive sleep.** Copy the opencode
  history: a create and restore route, a capture point at each place listed
  under Snapshots, and the `/ready` gate if boot must restore it. The
  per-session snapshot only carries `outputs/` and `attachments/`.
- `pod-setting` **A pod setting.** Change
  `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`. Add to
  `_overlay_dynamic_fields` only a value that differs per pod
  ([[#pod-fields-in-helm]]). A new Kubernetes API call needs its verb in
  `deployment/helm/charts/onyx/templates/sandbox-rbac.yaml` ([[#pods-watch-rbac]]).
- `sandbox-backend` **A sandbox backend.** Copy `DockerSandboxManager`; list the backends with
  `git grep -n 'class .*SandboxManager' backend/onyx/server/features/build/sandbox/`.
  Register it in `backend/onyx/server/features/build/sandbox/factory.py:get_sandbox_manager` and set
  `supports_opencode_history_persistence` ([[#history-persistence-flag]]).
- `investigate-craft-fails-to-start` **Investigate "Craft fails to start".** Read the user's `Sandbox` row:
  `PROVISIONING` that does not end points to the pod wait, `FAILED` to a
  provision error in the API server log. On Kubernetes, run
  `kubectl get pods,events -n onyx-sandboxes` and read the `sandbox-init` and
  `sidecar` container logs. A provision error with a 403 `ApiException`
  from the pod watch means `pods:watch` is missing ([[#pods-watch-rbac]]).
- `setup-sleep-wake-test` **Set up a sleep and wake test.** Lower `SANDBOX_IDLE_TIMEOUT_SECONDS`, wait
  for a sweep, and confirm the pod is gone and the `Sandbox` row is
  `SLEEPING`. Send a message to the same session and confirm its outputs come
  back. For a local kind cluster, use the `onyx-craft-dev` skill and
  `deployment/helm/dev/README.md`.

---

## Verification

- Unit: `backend/tests/unit/onyx/server/features/craft/sandbox/`.
- Lifecycle, sweep and snapshots with real Postgres and Redis:
  `backend/tests/external_dependency_unit/craft/`.
- Real cluster: `backend/tests/integration/tests/craft/k8s/` (kind setup in
  `deployment/helm/dev/README.md`). Only these tests catch
  [[#pods-watch-rbac]].
- Network posture: `backend/tests/integration/tests/craft/docker_e2e/`.
