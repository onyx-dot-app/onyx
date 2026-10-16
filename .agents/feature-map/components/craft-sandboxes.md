# Craft Sandboxes

> Shared Firecracker execution for Craft sessions: launcher lifecycle,
> guest helper calls, workspace setup, snapshots, managed content, and reaping.

**Verified against:** `6d012dd2d3` (2026-10-12)
**Domain:** craft
**Edition:** CE
**Owns:**
`backend/onyx/server/features/build/sandbox/` (`manager.py`, `runtime.py`,
`kubernetes_runtime.py`, `exec.py`, `k8s_client.py`, `models.py`, `labels.py`,
`session_workspace.py`, `snapshot_manager.py`, `serve_transport.py`,
`nextjs_dev.py`, `user_library.py`),
`backend/onyx/server/features/build/sandbox/image/guest/` (`__main__.py`,
`supervisor.py`, `input.py`, `operations.py`, `snapshot.py`, `opencode_history.py`,
`filesystem.py`, `outputs_manifest.py`, `extract.py`, `security.py`,
`models.py`),
`backend/onyx/server/features/build/sandbox/image/Dockerfile`,
`backend/onyx/server/features/build/sandbox/image/firewall-init.sh`,
`deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`,
`deployment/helm/charts/onyx/templates/sandbox-image-prepuller.yaml`,
`deployment/helm/charts/onyx/templates/network-policy-sandbox*.yaml`,
`deployment/firecracker/install-pinned-firecracker.sh`,
`deployment/helm/dev/refresh-images.sh`,
`deployment/helm/dev/firecracker-ci.sh`,
`deployment/helm/dev/craft-up.sh`, `deployment/helm/dev/k8s-up.sh`,
`deployment/helm/dev/values-localdev.yaml`,
`docs/craft/dev/local-kubernetes.md`,
`docs/craft/infra/firecracker.md`

**Read first:** `[[craft-sessions]]` for the user-facing session and turn
flow, `[[craft-external-apps]]` for proxy identity and approvals, and
`docs/craft/infra/firecracker.md` for node prerequisites.

---

## 1. What the user experiences

Users start a Craft session and get an isolated workspace. The agent can write
files, install packages, call connected apps through the egress proxy, run
`opencode serve`, and expose generated app previews. The runtime details are
hidden unless provisioning fails or the sandbox is idle-reaped.

The isolation boundary is a Kata Firecracker VM. The implemented Kubernetes
launcher selects it through `runtimeClassName`. The shared runtime interface has
one implemented launcher. Docker and Compose do not support Craft.
The original Docker/runc sandbox and sidecar process are removed.

---

## 2. Surfaces

### Python runtime

| File | Role |
|---|---|
| `manager.py` | Concrete `SandboxManager`, lazy singleton, high-level lifecycle API. |
| `runtime.py` | Typed launcher and guest-operation protocol, plus explicit runtime selection. |
| `kubernetes_runtime.py` | Kubernetes resources, legacy-topology guards, and exec target resolution. |
| `k8s_client.py` | Kubernetes client loading and typed API access. |
| `exec.py` | Root-helper exec protocol into the main sandbox container. |
| `serve_transport.py` | Streaming transport to `opencode serve` on port `4096`. |
| `session_workspace.py` | Workspace and generated-app setup. |
| `snapshot_manager.py` | FileStore-backed snapshot create and restore orchestration. |
| `backend/onyx/server/features/build/sandbox/image/guest/` | Code shipped into the sandbox image for privileged filesystem work. |

### Helm

| Template | Role |
|---|---|
| `sandbox-podtemplate.yaml` | Static pod shape. Python overlays only per-sandbox dynamic values. |
| `sandbox-image-prepuller.yaml` | Warms the sandbox image on the same RuntimeClass and node pool. |
| `network-policy-sandbox*.yaml` | Default deny, API/worker ingress, proxy egress, and preview ports. |
| `sandbox-rbac.yaml` | Lets api_server create/read/delete sandbox namespace resources and exec into pods. |

### Environment / configuration

| Variable | Owner | Effect |
|---|---|---|
| `ENABLE_CRAFT` | backend + Helm | Enables Craft surfaces and sandbox templates. |
| `CRAFT_SANDBOX_RUNTIME` | backend + deployment | Only `kubernetes_firecracker` is accepted and is the default. Other values fail without a fallback. |
| `SANDBOX_NAMESPACE` | backend + Helm | Namespace for sandbox pods, Services, Secrets, PodTemplate, and CA projection. |
| `SANDBOX_IDLE_TIMEOUT_SECONDS` | backend | Idle-reap threshold. |
| `SANDBOX_NEXTJS_PORT_START`, `SANDBOX_NEXTJS_PORT_END` | backend + Helm | Preview port range. |
| `ONYX_SERVER_URL` | backend + Helm | Internal Onyx URL allowed through the proxy and written into sandbox config. |
| `sandboxPod.runtimeClassName` | Helm | Exact value `kata-fc`; must match the installed Firecracker RuntimeClass. |

Image, pull policy, service account, resource requests, placement, probes, and
security context are Helm values. Do not add Python defaults for them. Both the
firewall init container and the main container need `SANDBOX_PROXY_HOST` and
`SANDBOX_PROXY_PORT`; the main `ca` path resolves the proxy host too.

---

## 3. Data model

`Sandbox` is the durable DB row for a user's sandbox. It stores the user,
tenant, status, pod name, service name, auth secret name, preview password,
heartbeat/attempt metadata, and encrypted scoped Onyx PAT.

`BuildSession` rows point at a user's active sandbox through the provisioning
flow. Session state, OpenCode session ids, user-library sync state, and approval
state live in their component-owned tables.

The sandbox manager does not own DB writes directly. Session and lifecycle
callers pass resolved rows and persist state changes through their own DB
helpers.

---

## 4. How it works

### Provisioning

1. The session layer asks `get_sandbox_manager()` for the singleton manager.
2. The manager allocates full UUID-based resource names.
3. Runtime reads the Helm PodTemplate from `SANDBOX_NAMESPACE`.
4. Python overlays dynamic labels, Secret refs, auth values, and proxy host
   aliases.
5. Runtime creates the auth Secret, Pod, and Service.
6. Kubernetes schedules the pod with exact `runtimeClassName: kata-fc`.
7. The firewall init container runs with `NET_ADMIN`.
8. The main container installs the proxy CA into its own rootfs and starts the
   guest supervisor.
9. Probes wait for TCP readiness on `4096`.
10. The manager verifies authenticated OpenCode HTTP before it returns success.

Runtime health uses Pod readiness and authenticated OpenCode HTTP. A busy exec
transport must not cause recovery of a healthy VM. All helper RPCs attach stdin.
Direct manager health tests run inside the API pod; CRI port-forward reaches
the host CNI namespace, not the guest listener.
Protocol2 sends bounded64KiB frames and a zero-length terminator, without CRI
stdin EOF. `run.has_stdin` records application payload presence. User commands
receive ordinary EOF from a completed temporary input file.

Readiness polls the Pod within the provisioning deadline. A Kubernetes watch
must not inherit the client's shorter REST read timeout.
OpenCode readiness counts metadata reads, retries, and password refresh in one
deadline. Authenticated `/global/health` avoids generating the OpenAPI document.
Each probe uses the smaller of the remaining budget and configured connect timeout.
Late success is rejected.
Synchronous metadata reads and HTTPX I/O phases are not hard wall-clock cancellation.

The manager rejects legacy short-name or sidecar-shaped pods before recovery.
That protects unsnapshotted work during cutover from the old implementation.

### Guest helper

The api_server uses Kubernetes `exec` to run:

```text
/opt/onyx-guest/venv/bin/python -I -m onyx_guest
```

The helper owns privileged filesystem operations, managed content pushes,
snapshot create/restore, opencode history, directory listing, and output
manifest reads. It drops untrusted work to UID/GID 1000.
Bootstrap and status stay standard-library-only. User operation imports occur
after privilege drop, avoiding duplicate model and archive initialization.

There is no raw exec path for ordinary shell work outside this helper protocol.
The runtime accepts helper operations and metadata, not arbitrary helper argv or
wire options. The Kubernetes adapter checks the current pod before framed exec.
The template declares protocol2 before dynamic overlays. Python resource and
status checks derive their version from the guest package. Old resources are
rejected before payload upload; a status mismatch remains a provisioning failure.
Boot and internal history-child operations are not public runtime helper calls.

Command failures kill and reap the command's process group, including outer
timeouts. Preview launches own a process group. Cleanup verifies the recorded
PID and workspace before signaling. It uses the original pidfd for group signals,
then verifies that no live member remains if the leader exits during cleanup.
This requires Linux guest kernel 6.9 or later. The pinned Kata 4.2 guest is 6.18.35.
Run budgets include request imports and input preparation. Command expiry
returns 124 with bounded stderr. The watchdog reserves 11 seconds for cleanup.
History timeout cleanup signals the owned child as UID1000, restores root identity,
and reaps before releasing the lock. The root helper does not gain `CAP_KILL`.

### Networking

The sandbox main process listens on `OPENCODE_SERVE_PORT` (`4096`). Preview
ports use `SANDBOX_NEXTJS_PORT_START` through `SANDBOX_NEXTJS_PORT_END`.

NetworkPolicies keep sandbox ingress closed except for api_server,
scheduled-task workers, and optional Telepresence development labels. Egress
still goes through `sandbox-proxy`, which resolves sandbox identity from
Kubernetes pod labels.

Docker attaches bridge veths after the Kata VM starts. Kata's Docker fix uses
device hotplug, which this Firecracker integration does not support. A boot-only Docker proof
does not establish guest networking or a supported Compose deployment.

### Snapshots and managed content

Session snapshots remain FileStore archives. Session archive creation and
sandbox file downloads are capped at 100 MiB. The guest helper now reads and
writes the pod-local filesystem directly.
Session archives also have a 500 MiB expanded limit, including each restored
hardlink copy. New archives store linked regular files independently. Legacy
GNU tar hardlinks can copy only preceding regular members within allowed roots.
Legacy generated dependency/build entries are skipped after path validation.
Their regular archive data can still supply retained user hardlink copies.
Symlinks, unsafe or duplicate paths, and linked or forward targets are rejected.
Directory modes apply after descendants. Read-only root modes apply after
promotion. Workspace cleanup can repair owner directory permissions and retry
once without following symlinks.

OpenCode history is a separate archive with a 1 GiB compressed limit, a 4 GiB
expanded limit, and a 100,000 member limit. Creation and restore enforce the
same limits. Corrupt restored history fails before replacing current data.
Backend live-history snapshotting starts only after the startup history restore
gate opens.

Managed skills and MCP config are pushed to `/workspace/managed`. Sessions link
or read from that root-owned managed tree. Snapshot format changes must remain
backward-compatible with existing FileStore archives.

### Reaping and recovery

Idle reaping snapshots first and terminates only after the snapshot path
returns success. Recovery is fail-closed when the live pod shape is unsafe or
when a snapshot cannot be made.

Creation-failure cleanup only targets resources returned by the create call,
including admission mutations. Teardown wait failures must retry deleted pods
instead of assuming success.

Cutover requires draining and snapshotting old sidecar pods with the old
release before upgrading.
The same rule applies to protocol1 helpers. Stop old API and worker replicas
before installing the protocol2 template and matching guest image. Do not mix
old provisioners with a new template or relabel an old pod into compatibility.

---

## 5. Security and storage invariants

- **RuntimeClass is exact.** `kata-fc` is the only supported value. Do not allow
   alternate classes or silently run Craft on `runc`.
- **RuntimeClass is not proof.** Verify the pod boots and serves real Craft
   traffic before claiming Firecracker coverage.
- **Helm launcher and exec prerequisites are checked.** Enabled Craft requires
   `kubernetes_firecracker` and Kubernetes 1.30 or newer. Framed helpers request
   only WebSocket v4 and bypass API-server WebSocket-to-SPDY translation.
   Raw stdin tests retain v5 EOF and require the default-enabled
   `TranslateStreamCloseWebsocketRequests` gate.
- **No sidecar.** Do not reintroduce push ports, sidecar clients, or
   signature keys.
- **Main container has no `NET_ADMIN`.** Firewall setup belongs to the init
   container only.
- **No workspace/history `emptyDir`.** Rootfs devmapper capacity is the
   writable storage boundary.
- **Kubelet `ephemeral-storage` does not enforce the rootfs block quota.**
   Size and monitor devmapper separately.
- **Legacy pods are protected.** A recovery guard is safer than deleting
   old unsnapshotted work.
- **The prepuller must use the same RuntimeClass.** Warming `runc` nodes gives
   false confidence.
- **The manager stays out of the DB.** Keep persistence in session/lifecycle
   layers.

---

## 6. Cross-component dependencies

| Change | Also check |
|---|---|
| PodTemplate security context or containers | Helm render tests, node RuntimeClass, firewall behavior, proxy CA install, port `4096` readiness. |
| RuntimeClass value | `sandbox-podtemplate.yaml`, `sandbox-image-prepuller.yaml`, Firecracker node labels, local cluster docs. |
| Proxy env wiring | both firewall init and main containers; `firewall-init.sh ca` needs `SANDBOX_PROXY_HOST` and `SANDBOX_PROXY_PORT`. |
| Guest helper request or response models | `exec.py`, `backend/onyx/server/features/build/sandbox/image/guest/`, API model imports, snapshot and directory callers. |
| Snapshot archive layout | `snapshot_manager.py`, `backend/onyx/server/features/build/sandbox/image/guest/`, existing FileStore snapshots, recovery paths. |
| OpenCode history limits | create and restore paths, corrupt-history handling, backend gate that waits for restored history before snapshotting live history. |
| Preview port range | Helm PodTemplate, Service generation, NetworkPolicies, webapp proxy, frontend preview URLs. |
| Sandbox names or labels | proxy identity lookup, NetworkPolicy selectors, old-pod protection, cleanup jobs. |
| Managed content path | `skills/push.py`, session config generation, guest helper, `[[skills]]`. |
| Reaping logic | snapshot fail-closed behavior, Celery cleanup task, old-pod cutover guard. |

---

## 7. Migration and cutover notes

Before upgrading from the old sidecar release, drain traffic and snapshot live
sessions with the old release. Inspect the old OpenCode history limits before
migration. Clear restore failures must preserve the saved history archive. The
new manager refuses unsafe auto-recovery of old pod shapes. It does not fake
readiness for old pods.

Production node pools must size containerd devmapper for the real workspace
quota. For a 50 GiB workspace, use `base_image_size >= 64GiB`, reserve the
thin-pool capacity physically, monitor it, and configure auto-extension.

---

## 8. Verification map

Run only the gates that match the change:

- Helm render/lint for PodTemplate, prepuller, NetworkPolicy, RBAC, and
  RuntimeClass defaults.
- Integration tests that create a sandbox pod on a KVM-capable Kubernetes
  cluster.
- The four EOF cases in
  `backend/tests/integration/tests/craft/k8s/test_kubernetes_sandbox.py` must
  preserve delayed stdout with empty and finite stdin, exact binary output,
  and delayed stdout and stderr with exit code 7. Run these with the normal live
  fixtures. Static checks and boot-only smoke tests do not qualify this path.
- `test_guest_run_background_children_follow_exit_status` must preserve exit
  status and stderr, prevent failed-command descendant writes, and retain
  successful background commands.
- The guest archive cases in `test_snapshot_restore.py` cover old GNU tar
  hardlinks, materialized file contents, nested and root read-only modes,
  repeated restore, cleanup, unsafe targets, duplicates, and expanded limits.
  Normal application-dependent fixtures remain the full integration gate.
- Firecracker CI uses linux/amd64 nested virtualization and requires KVM.
  Fresh development pools default to an `8GB` rootfs and `16G` data file for
  the full image and workspace bootstrap. Production quota sizing is separate.
  Image cleanup removes the build-time Node compile cache before credentials
  exist; credential tests retain their complete scan and positive controls.
  Fresh kind nodes need the checksum-pinned official containerd 2.1.1 daemon
  because the stock kind build excludes devmapper. Setup preserves the same
  source revision, `ctr`, and runc shim, and refuses existing pools/backing files.
  The kind config retains compressed image layers so default overlayfs pulls
  can later unpack into devmapper. Retained layers consume disk on the disposable kind node.
  Setup and containerd use `DM_DISABLE_UDEV=1` for pool and thin-device nodes
  because the pinned kind node does not run udev.
  The dedicated disposable test-host profile shares writable host `/dev` with
  private propagation and requires `ONYX_FIRECRACKER_DEDICATED_HOST=true`.
  This exposes Kata's dynamic canonical device paths and permits shared device
  metadata changes. Never use that kind profile on shared or production hosts.
  Its disposable kind cluster installs checksum-pinned Calico 3.31.7 before
  Kata, with the default kind CNI disabled. Network tests must still prove
  direct traffic is denied; CNI readiness alone does not prove isolation.
  Every integration shard routes API calls through the frontend. The
  session-provisioning shard then runs Craft browser streaming, file, reload,
  cancellation, and attachment checks against the same cluster. Browser turns
  use the existing scripted mock LLM, but execute real guest tools.
  Session-provisioning tests repeat managed archive transfers from the API pod
  and check file digests and unchanged pod and container identity.
  The probe uses the production archive builder, helper, and mounted service account.
  Missing real-model credentials fail before paid prerequisite jobs. Manual
  `product_only=true` dispatches run only the session/browser setup probe with
  a distinct status name. They do not qualify the migration; the full suite
  must run afterward. Pull requests and default dispatches retain all shards.
  CI builds the sandbox with `ENABLE_SKILLS=true` so the production document
  shard exercises the Office, PDF, JavaScript, and native image dependencies.
  Each shard uploads JUnit XML with exact test names, receipt properties, and
  successful stdout. The report uses `xunit1` for `record_property` compatibility
  and excludes captured stderr and pytest logs. Report artifact names include
  the shard, run ID, and run attempt.
  CI-only `SANDBOX_TEST_SHIM_PPROF=true` enables the existing root-only Unix
  profiler. Failure capture emits bounded counts for one owned sandbox, not
  raw stacks. Production profiling stays off. A native stdin control must
  prove the capture before its results support a diagnosis.
  Workflow configuration checks do not prove RunsOn capacity or live acceptance.
- Craft frontend E2E that starts a session, streams a turn, writes files,
  serves a preview, snapshots, restores, and reaps.
- Proxy integration tests when labels, Service names, proxy CA, or
  NetworkPolicies change.

Do not report E2E success unless the frontend flow actually ran.

---

## 9. Local development and footguns

Firecracker requires Linux KVM. Docker Desktop and ordinary macOS kind clusters
do not validate the runtime. Use a Linux x86_64 host or nested-virtualization VM
for real VM tests.

The local Firecracker/devmapper profile uses a small sparse pool and rootfs.
It is a smoke-test profile, not production sizing guidance.

Local Craft setup requires an existing kind cluster with usable KVM and
vhost-vsock devices, healthy devmapper, and the `kata-fc` handler. It checks the
pinned Firecracker and jailer versions before builds or cluster changes.
Runtime preflight first rejects Kindnet and failed Kindnet reads in the selected context.
The fresh-host guide disables the default CNI and installs checksum-pinned Calico 3.31.7 before Kata,
with the same pod subnet and readiness checks as Craft CI.
`--skip-helm` is an ordinary non-Craft cluster-only path. It does not configure
Kata, install Onyx, or build guest images.
Craft requires a NetworkPolicy-enforcing CNI. Kindnet absence does not prove
policy enforcement. Run the real isolation suite before trusting the deployment.

The local Helm overlay owns backend and guest `:dev` images with
`IfNotPresent`. The Make image targets share one refresh script. Refresh refuses
existing sandbox pods, rolls all in-cluster backend deployments, and waits for
old backend pods to terminate. Only then does it import the guest into devmapper,
verify its exact CRI config ID and cache retention, and apply the complete Helm
PodTemplate with both images and the protocol label. A final namespace check
refuses success if a sandbox appeared. It never deletes sandbox pods. Stop the
host Onyx API, Celery workers, and beat before cutover. Restart them afterward.
IDE profiles select `CRAFT_SANDBOX_RUNTIME=kubernetes_firecracker`. Removed
backend image controls and push signing keys do not configure guest pods.

Stock Kata 4.2.0's Go runtime can truncate exec output after stdin EOF, even
when the command exits with code 0. Local arm64 checks also reproduced lost
stderr with code 7 and a binary transfer timeout. The experimental fix in
[Kata PR #13643](https://github.com/kata-containers/kata-containers/pull/13643)
is not installed by the CI helper. See `docs/craft/infra/firecracker.md` for
current qualification limits before promoting a runtime.
Protocol2 avoids CRI stdin EOF using finite helper frames. A three-case diagnostic
passed on the released shim and pinned Firecracker1.17, but bypassed normal
bootstrap. Normal Craft and browser acceptance remain open.

Docker's late network setup can leave a Firecracker guest with only loopback.
Kata's Docker integration is tested with QEMU, not Firecracker. See the
[Kata installation guide](https://raw.githubusercontent.com/kata-containers/kata-containers/4.2.0/docs/installation.md)
and [virtualization limits](https://raw.githubusercontent.com/kata-containers/kata-containers/4.2.0/docs/design/virtualization.md).
