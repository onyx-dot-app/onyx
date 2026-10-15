# Craft sandbox runtime

Craft uses one Firecracker runtime interface beneath the shared sandbox manager.
The Kubernetes launcher runs pods through `kata-fc`. The Docker Firecracker
launcher is under implementation; its network and identity checks remain required.
The original Docker/runc sandbox, push daemon, and in-pod sidecar are removed.

## Important decisions

- `SandboxManager` stays concrete. Launchers share guest, workspace, snapshot,
  and serve behavior through the small `SandboxRuntime` protocol.
- The sandbox pod has one main container plus one firewall init container.
- The firewall init container is the only sandbox container with `NET_ADMIN`.
- The main container runs as root only to supervise the guest helper and drop
  untrusted work to UID 1000.
- The RuntimeClass is exactly `kata-fc`; do not allow alternate classes or a
  `runc` fallback.
- Writable Craft state lives on the Kata rootfs. Do not add workspace or
  history `emptyDir` volumes.
- New code protects legacy pods by rejecting their old topology. Drain and
  snapshot them with the old release before upgrading.

## Runtime contract

`manager.py` owns guest operations, snapshots, and OpenCode communication.
`runtime.py` defines launcher operations and explicit selection.
`kubernetes_runtime.py` owns Kubernetes objects and exec target resolution.
The session layer owns database state and lifecycle reservations. Celery calls
the manager when it reaps an idle VM.

The api_server talks to the sandbox through three channels:

1. Kubernetes create/read/delete for the Pod, Service, Secret, and labels.
2. Kubernetes `exec` into the main container to run the immutable root helper:
   `/opt/onyx-guest/venv/bin/python -I -m onyx_guest`.
3. HTTP to `opencode serve` on port `4096`, plus generated preview ports.

The guest helper owns filesystem operations, snapshots, managed content pushes,
and opencode history. It runs privileged setup as root, then drops user work to
UID/GID `1000`. Shared response models live in `image/guest/models.py`.
Bootstrap and status use only the standard library. User request and archive
imports run after privilege drop.

Read operations leave stdin detached. Only payload operations attach stdin and
close it explicitly. This avoids a CRI stdin-close/output-forwarding failure.
`run` sets `has_stdin: true` only when the command has an input payload.
Health probes use authenticated OpenCode HTTP, not exec availability.

Command failures kill and reap the command's process group, including outer
timeouts. Preview launches own a process group. Cleanup verifies the recorded
PID and workspace before signaling. Forced cleanup kills that owned group.
Run budgets include request imports and input preparation. Command expiry
returns 124 with bounded stderr. The watchdog reserves 11 seconds for cleanup.

## Pod shape

Helm renders the static PodTemplate in
`deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`. Python only
adds per-sandbox names, labels, auth Secret references, and proxy host aliases.

The pod template must keep these invariants:

- `runtimeClassName` is exactly `kata-fc` and must not fall back to `runc`.
- The main `sandbox` container has only `SETUID`, `SETGID`, `SETPCAP`, and
  `CHOWN`.
- `sandbox-firewall` runs `/opt/onyx-guest/firewall-init.sh firewall` with
  `NET_ADMIN`.
- The main container installs the proxy CA into its own rootfs by running the
  same script with `ca`.
- The main container must receive `SANDBOX_PROXY_HOST` and
  `SANDBOX_PROXY_PORT`, because the CA path resolves the proxy host too.
- The proxy CA mount is read-only.
- There is no sidecar container, push port, shared handoff volume, or pod
  `fsGroup`.

NetworkPolicy still denies sandbox ingress by default. The api_server and
scheduled workers can reach `4096` and the preview port range. The egress proxy
still identifies sandboxes from Kubernetes pod labels.

## Storage and snapshots

The sandbox image creates root-owned immutable directories and user-owned
session directories under `/workspace`. Session archives and downloads are
limited to 100 MiB. Snapshots continue to use the existing FileStore archives,
but the guest helper now creates and restores them directly.

OpenCode history is separate from session archives. It allows at most 1 GiB
compressed, 4 GiB expanded, and 100,000 members. Snapshot creation and restore
validate the same limits. Corrupt restored history fails before replacing the
current data. The backend snapshots live history only after the startup history
restore gate has opened.

Production Firecracker capacity comes from the Kata rootfs block device. For a
workspace near 50 GiB, set the containerd devmapper `base_image_size` to at
least 64 GiB and reserve real thin-pool capacity on the node. Kubernetes
`ephemeral-storage` requests and limits do not enforce this rootfs block quota.
The physical devmapper pool must hold the promised capacity.

During cutover from the old sidecar implementation:

1. Run the old release.
2. Drain interactive traffic.
3. Snapshot live sessions and reap idle pods.
4. Upgrade the api_server and Helm release.

The new manager uses full UUID pod names and refuses unsafe recovery of old
short-name or sidecar-shaped pods. That guard prevents deleting unsnapshotted
work. Creation failures clean only resources returned by the create call,
including admission mutations, and teardown waits must fail closed so deleted
pods are retried instead of assumed gone.

## Configuration

Backend runtime configuration still reads:

- `ENABLE_CRAFT`
- `CRAFT_SANDBOX_RUNTIME`, default `kubernetes_firecracker`
- `SANDBOX_NAMESPACE`
- `SANDBOX_IDLE_TIMEOUT_SECONDS`
- `SANDBOX_NEXTJS_PORT_START`
- `SANDBOX_NEXTJS_PORT_END`
- `ONYX_SERVER_URL`
- sandbox proxy settings from `configs.py`

Helm owns image, service account, pull policy, runtime class, resources,
placement, and probe settings. Do not reintroduce Python defaults for those
values.
Only `kubernetes_firecracker` is accepted. Other launcher values fail without
a fallback. Docker and Compose do not support Craft.

## Local development

Firecracker needs Linux KVM. Docker Desktop and ordinary macOS kind clusters do
not provide a useful validation target.

Use a Linux x86_64 host or nested-virtualization VM for real tests. The current
local test profile uses a small sparse devmapper pool and rootfs. That profile
is for development only and is not a production capacity model.

## Verification

Useful gates for this package:

- Helm render checks for the sandbox PodTemplate and prepuller RuntimeClass.
- Integration tests that provision a real sandbox pod on a KVM-capable cluster.
- End-to-end Craft flows through the frontend after the cluster is ready.

Do not claim Firecracker coverage from `runtimeClassName` alone. Confirm the
pod is scheduled to the Firecracker RuntimeClass, boots, opens port `4096`, and
runs real user flows.
