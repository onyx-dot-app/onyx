# Craft Firecracker infrastructure

Craft sandboxes are mandatory Firecracker-backed Kubernetes pods. The Onyx Helm
chart renders a single-container sandbox PodTemplate that uses the `kata-fc`
RuntimeClass. The chart does not install Kata, Firecracker, KVM, containerd
devmapper, node labels, or node capacity.

Primary references:

- [Firecracker getting started](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)
- [Firecracker v1.17 release support](https://raw.githubusercontent.com/firecracker-microvm/firecracker/v1.17.0/docs/RELEASE_POLICY.md)
- [Firecracker v1.17 kernel policy](https://raw.githubusercontent.com/firecracker-microvm/firecracker/v1.17.0/docs/kernel-policy.md)
- [Kata Containers installation](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)
- [Kata with Firecracker](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-kata-containers-with-firecracker.md)
- [containerd devmapper snapshotter](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)

## Important decisions

- RuntimeClass is mandatory and exact. `kata-fc` is the only supported class;
  there is no alternate class or `runc` fallback.
- The sandbox pod has one main container and one firewall init container.
- The main container does not get `NET_ADMIN`.
- The firewall init container runs `/opt/onyx-guest/firewall-init.sh firewall`
  with `NET_ADMIN`.
- The main container runs the same script with `ca` to install the proxy CA into
  its own rootfs.
- Both init and main containers need `SANDBOX_PROXY_HOST` and
  `SANDBOX_PROXY_PORT`; CA install resolves the proxy host.
- The sidecar and push daemon are removed. Kubernetes `exec` reaches only the
  root helper in the main container.
- Rootfs block capacity is the production storage boundary. Kubernetes
  `ephemeral-storage` does not enforce the devmapper rootfs size.

## Node prerequisites

Each sandbox node must provide:

- Linux with KVM exposed at `/dev/kvm`.
- A Kata Containers install that registers a Firecracker RuntimeClass named
  exactly `kata-fc`.
- containerd configured for the Kata Firecracker runtime.
- containerd with the devmapper snapshotter built in and storage sized for Craft workspaces.
- A Linux guest kernel 6.9 or later for safe preview process-group cleanup.
- enough CPU and memory for each Firecracker VM plus the pod overhead.

Firecracker itself requires KVM access. Kata's Kubernetes installation guide
documents the supported RuntimeClass flow. Kubernetes only selects a runtime
handler from `runtimeClassName`; it does not prove that Firecracker booted.
Use a supported Firecracker release and check its host and guest kernel policy.
The CI bundle is a test pin, not a production version policy.

## Helm contract

Set `configMap.ENABLE_CRAFT=true` and use the normal Onyx chart. The chart
renders:

- `sandbox-podtemplate.yaml`
- `sandbox-image-prepuller.yaml`
- sandbox RBAC
- sandbox ingress and egress NetworkPolicies
- sandbox proxy CA projection

`sandboxPod.runtimeClassName` is `kata-fc`. The prepuller uses the same value
so it warms the same Firecracker-capable node pool. Do not rename the
RuntimeClass for Craft without changing the runtime contract and tests.

`values-firecracker.yaml` is a cluster overlay, not an installer. It selects
amd64 nodes and keeps RuntimeClass at `kata-fc`.

The chart requires Kubernetes 1.30 or newer and the `kubernetes_firecracker` launcher.
Sandbox exec uses WebSocket v5. Keep the API server's
`TranslateStreamCloseWebsocketRequests` feature gate enabled, its
[default since Kubernetes 1.30](https://github.com/kubernetes/kubernetes/blob/v1.30.0/pkg/features/kube_features.go).
The version check cannot inspect feature-gate overrides. Run the live exec tests before deployment.

## Pod shape

The sandbox pod has:

- one `sandbox` main container
- one `sandbox-firewall` init container
- no sidecar
- no push port
- no workspace/history `emptyDir`
- no `fsGroup`
- a read-only proxy CA mount

The main container runs as root to supervise the immutable helper:

```text
/opt/onyx-guest/venv/bin/python -I -m onyx_guest
```

The helper drops untrusted work to UID/GID 1000. The main container keeps only
`SETUID`, `SETGID`, `SETPCAP`, and `CHOWN`.

## Snapshot limits

Session archives and sandbox file downloads are capped at 100 MiB. Session
archives also have a 500 MiB expanded limit. Restored hardlink copies each
consume their source size from that limit.

New session archives materialize linked regular files. Legacy GNU tar archives
can reference preceding regular members within `outputs` and `attachments`.
Restore copies their contents without creating filesystem hardlinks. It rejects
unsafe targets, forward references, linked targets, duplicate paths, symlinks,
and special files outside excluded generated paths. Legacy dependency/build
trees and runtime scratch files are skipped, while user aliases retain their
archived regular-file contents. Final directory modes are retained after extraction and
promotion. Read-only workspace cleanup has one bounded permission-repair retry.

OpenCode history is stored separately from session snapshots and is capped at:

- 1 GiB compressed
- 4 GiB expanded
- 100,000 archive members

Snapshot creation and restore enforce the same OpenCode history limits. A
corrupt restored history archive fails before it replaces current data. Backend
history snapshotting starts only after the startup history restore gate opens.

## Storage capacity

Production Craft uses the Kata rootfs block device for writable workspace
state. Size the containerd devmapper pool for the actual workspace quota.

Use these production rules:

- set `base_image_size` to at least 64 GiB for a workspace near 50 GiB
- physically reserve the thin-pool capacity on the sandbox node pool
- monitor thin-pool usage
- configure thin-pool auto-extension
- do not rely on Kubernetes `ephemeral-storage` limits for devmapper rootfs
  enforcement

The shared local and CI test setup defaults to a `16G` sparse devmapper data
file, a `1G` metadata file, and an `8GB` rootfs. These fresh-pool defaults leave
more room for the full sandbox image and workspace bootstrap.
`DEVMAPPER_DATA_SIZE`, `DEVMAPPER_META_SIZE`, and `DEVMAPPER_BASE_IMAGE_SIZE`
override the defaults. This is a developer test profile only. Production must
reserve physical devmapper pool capacity for the full promised workspace quota.

## Cutover from the sidecar release

Do this before installing the Firecracker release:

1. Keep the old release running.
2. Drain new interactive Craft traffic.
3. Inspect old OpenCode history limits and snapshot live sessions with the old
   release. A clear restore failure must preserve the last saved history
   archive.
4. Reap or manually terminate idle old pods after their snapshots land.
5. Upgrade Helm and the api_server.

The new manager uses full UUID pod names. It detects old short-name and
sidecar-shaped pods and refuses unsafe auto-recovery. This protects
unsnapshotted work. It does not make old pods ready, and it does not fake
Firecracker coverage for them. If creation fails, cleanup only targets
resources returned by the create call, including admission mutations. Teardown
wait failures must retry deleted pods rather than assume success.

## Local development notes

Docker Desktop and ordinary macOS kind clusters do not expose the needed KVM
device. Use a Linux x86_64 host or a nested-virtualization VM.

Observed local profile:

- The local test profile uses 4 vCPU and 1536 MiB.
- VM boot and binary transfers passed; full Craft startup has not passed locally.
- 2560 MiB booted a direct, unjailed Firecracker VM in 134 seconds.
- That 2560 MiB test was not a jailed Kata Kubernetes validation.
- arm64 is manual and unsupported by the current Kata Kubernetes CI path.

## CI helper

`deployment/helm/dev/firecracker-ci.sh` is the static nested-virtualization CI
setup. It pins Kata deploy 4.2.0, requires linux/amd64 with KVM and
vhost-vsock, configures devmapper, installs `kata-fc`, replaces Kata's bundled
Firecracker and jailer with the paired v1.17.0 binaries from
`deployment/firecracker/install-pinned-firecracker.sh`, and validates with a
smoke pod that checks boot IDs and the live Firecracker executable.

The stock kind daemon excludes devmapper. Node setup installs the checksum-pinned
official containerd 2.1.1 daemon at the same source revision. It leaves `ctr` and
the runc shim unchanged. Existing pools and backing files prevent replacement.
The kind config retains compressed layers for devmapper unpack after overlayfs pulls, using disk on the disposable node.
This helper targets dedicated, disposable Linux/amd64 test hosts or VMs, never shared workstations or production nodes.
It requires `ONYX_FIRECRACKER_DEDICATED_HOST=true` as an explicit acknowledgement.
The privileged node shares writable host `/dev` with private mount propagation.
Systemd can change shared device permissions and ownership; private propagation does not prevent these metadata changes.
Host and node devtmpfs expose the dynamic `/dev/dm-N` paths that Kata derives from sysfs.
The pinned kind node does not run udev. Setup and containerd use
`DM_DISABLE_UDEV=1` so libdm creates pool and thin-device nodes directly.
Setup verifies the owned pool by name, path, and block-device type before restart.
Before guest smoke, the helper creates one temporary snapshot, verifies its canonical device, then removes that snapshot.

The installer verifies architecture-specific SHA-256 checksums. This verifies
the binary pin. Runtime compatibility and Craft readiness need separate live
validation. The CI helper uses the stock Kata 4.2.0 shim and does not install
[Kata PR #13643](https://github.com/kata-containers/kata-containers/pull/13643).

This script is not proof that the current CI provider has nested virtualization
capacity. It fails closed when KVM, modules, RuntimeClass, or smoke validation
are missing.

## Current qualification status

As of 2026-10-14, the [Kata 4.2.0 bundle](https://raw.githubusercontent.com/kata-containers/kata-containers/4.2.0/versions.yaml)
lists Firecracker 1.12.1, guest kernel 6.18.35, and containerd 2.3 with a 1.7
minimum. The Firecracker 1.17.0 override needs separate qualification.
Containerd 2.4.1 compatibility remains unverified by that published bundle.

Firecracker's [release policy](https://raw.githubusercontent.com/firecracker-microvm/firecracker/v1.17.0/docs/RELEASE_POLICY.md) provides critical and security fixes for at least
six months after a release. Firecracker 1.12 support ended on 2025-12-17.
The bundled version therefore does not provide a supported downgrade path.
Production also requires the applicable [host and guest kernel policy](https://raw.githubusercontent.com/firecracker-microvm/firecracker/v1.17.0/docs/kernel-policy.md).

The local arm64 profile reproduced delayed stdout and stderr truncation after
stdin EOF with stock Kata 4.2.0's Go runtime, for exit codes 0 and 7. A binary
transfer also timed out. An experimental shim from the open PR #13643 at
`293f5c7` passed the local exec checks. That patch remains a local experiment.
No production fork is approved, and CI does not install the patch.

A real Craft session POST failed at the 180-second readiness deadline.
A 600-second guest diagnostic also failed with a live OpenCode executable and
guest-local TCP port `4096` returning `ECONNREFUSED`. Full Craft and browser
flows remain unverified.
A normal-logging diagnostic on host kernel 6.18.56 also failed to become ready.

A three-case held-stdin diagnostic later passed on stock Kata4.2.0 and pinned
Firecracker1.17.0. It preserved binary bytes, delayed output, exit7, guest user
isolation, and a following root helper status call. The probe bypassed normal
bootstrap and used its own uploader. It does not qualify production helper or
Craft behavior.

The production protocol2 change uses finite helper input frames instead of CRI
stdin EOF. Frames have a four-byte big-endian length, at most64KiB of data, and
a zero-length terminator. All RPCs attach stdin, including payload-free calls.
User commands receive the existing completed temporary file with ordinary EOF.
Protocol2 runtime and normal application flows still need real VM verification.

## Helper protocol cutover

Snapshot and drain old sandboxes using their existing release before upgrading.
Stop old API and scheduled-worker replicas before applying the protocol2 template
and matching guest image. Resume requests only after all provisioners use the new
release. A rolling mix can let old provisioners overwrite the new protocol label.

Set `SANDBOX_CONTAINER_IMAGE` to the matching built image. Use a digest for a
production release. The static template label declares protocol2; it does not
prove the image contents. Provisioning must verify the helper's reported version
and fail with owned-resource cleanup on mismatch.
Never relabel an old live pod or delete unsnapshotted work to bypass a guard.

## Verification

Minimum real validation:

1. `helm template` renders the sandbox PodTemplate and prepuller with the same
   RuntimeClass.
2. `kubectl get runtimeclass kata-fc` succeeds.
3. A sandbox pod schedules on the Firecracker node pool.
4. Guest exec preserves exact stdout, stderr, binary bytes, and exit status
   after the input terminator, including delayed output. Commands still observe
   ordinary stdin EOF from their completed input file.
5. The pod boots and exposes `opencode serve` on port `4096`.
6. A real Craft frontend flow creates a session, streams a turn, writes files,
   serves a preview, snapshots, restores, and reaps.

`backend/tests/integration/tests/craft/k8s/test_kubernetes_sandbox.py` contains
four permanent EOF regression cases. They cover empty and finite stdin,
binary output, and delayed stdout and stderr with exit code 7. Static checks
passed. A separate regression covers failed-command descendant cleanup and
successful background commands.
Run these cases against protocol2 without sending CRI stdin EOF. Also test
unknown-length input, malformed frames, early errors, history retries, and empty RPCs.

Before the protocol2 change, all six helper cases passed through the real manager and Kubernetes exec path
on a fixed-HTTP Firecracker control VM. That control bypasses application
provisioning and database session fixtures. The normal live fixtures have not
run these cases, and the control does not qualify full Craft behavior.

Production promotion requires these live checks and full Craft flows, plus an
owned runtime policy with supported releases and kernels. Binary checksums,
boot IDs, and local exec experiments do not establish application qualification.

Do not report E2E success unless the frontend flow actually ran.

### CI product gate

`.github/workflows/pr-craft-k8s-tests.yml` uses Linux x86_64 runners with KVM.
Its disposable kind cluster installs checksum-pinned Calico 3.31.7 before Kata.
The default kind CNI is disabled because it does not enforce NetworkPolicies.
Run the direct-egress integration tests to prove denial. CNI readiness is not
isolation evidence.

Each integration shard runs the frontend and routes API requests through it.
After the session-provisioning shard passes, the same cluster runs the Craft
browser specs with one worker, no retries, and Craft required to be enabled.
The existing scripted mock LLM runs in an ordinary test Pod using the backend
image and mounted test source. Browser tests still execute real sandbox tools.
They cover streaming, file preview/download, reload, cancellation, and attachments.
Generated-app preview, restore, reaping, and network isolation have separate
integration gates.

Missing real-model credentials fail before paid prerequisite jobs. Manual
`product_only=true` dispatches run the session/browser setup probe only.
Its `craft-k8s-product-probe` status does not qualify the migration.
Run the full suite afterward. Default dispatches and pull requests retain all shards.
Runtime setup streams the pinned installer into the owned kind node through
Docker exec stdin. It does not copy an executable into the node's temporary directory.

This workflow is prepared but has not qualified the migration. The RunsOn labels
request nested virtualization; the deployed runner must expose usable KVM.
Configuration tests and Playwright collection do not prove a live product flow.
