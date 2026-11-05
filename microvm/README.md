# microvm

Go module that runs Onyx Craft micro-VMs on Firecracker. Linear project P-ENG-224.

- `cmd/host-agent/`: the host agent. One process per Craft node. It runs the Firecracker VMs.
- `proto/hostagent/v1/`: the gRPC API of the host agent, with the generated Go code.
- `internal/`: the agent packages.
- `cmd/guest-daemon/`: the guest daemon (runs inside each VM; see its README). `cmd/egress-relay/`: the in-guest egress relay.

Nothing deploys the agent yet. The Helm DaemonSet (ENG-4583) adds it behind `SANDBOX_RUNTIME=firecracker`.

## Host agent

### API

`proto/hostagent/v1/hostagent.proto`:

| Call | What it does |
|---|---|
| `Create(sandbox_id, attempt, template, vcpus, mem_mib, scratch_gib, tenant_id, sandboxd_key)` | Restores a VM from a template snapshot and returns it with its `generation`. With `sandboxd_key`, it installs that key in the guest daemon (`SetKey` over vsock, up to 10 s) before it returns a running VM (see Guest daemon pass-through). A repeat call with the same `(sandbox_id, attempt)` returns the existing VM. A different attempt for a sandbox with a VM on the node returns `ATTEMPT_CONFLICT`. An attempt that is not newer than a stopped one returns `STALE_ATTEMPT`. |
| `Stop(sandbox_id, attempt, generation)` | Stops the VM only if all three match. A repeat Stop of the same instance succeeds with `already_stopped`. |
| `CloseConnections(sandbox_id, attempt, generation)` | Closes every relay connection of the VM. New connections still work. Stop and VM exit also close them. |
| `List()` | Every VM that the agent knows about, with its state (`STARTING`, `RUNNING`, `EXITED`). |
| `NodeInfo()` | Total and free memory, free disk, VM count, templates on disk (with their key and `compatible`), CPU model, Firecracker, host kernel and guest kernel versions. |
| `BuildTemplate()` | Builds the node's template from `--rootfs-dir` if no valid one for its key is there, then removes old templates (see Templates). |
| `CloseConnections(sandbox_id, attempt, generation)` | Closes the VM's egress relay connections (see Egress relay). |
| `Dial(sandbox_id, guest_port, generation)` | Byte stream to a guest vsock port (see below). |
| `craft.sandboxd.v1.Sandboxd/*` | Any guest daemon call, forwarded to the VM named by `x-sandbox-id` (see Guest daemon pass-through). |

Errors are typed. Each error is a gRPC status with one `google.rpc.ErrorInfo` detail: the domain is
`hostagent.craft.onyx.app` and the reason is an `ErrorReason` name, for example `CAPACITY_MEMORY`,
`TEMPLATE_MISSING` or `ATTEMPT_CONFLICT`. `internal/apierr` maps each reason to a gRPC code.

Rules for the Create parameters:

- `vcpus` and `mem_mib` must equal the template's. A snapshot restore keeps the template's shape
  (`TEMPLATE_SHAPE_MISMATCH`).
- `scratch_gib` must be at least the template's scratch size, and at most `--max-scratch-gib`. The scratch
  disk can only grow. The agent extends the disk and tells Firecracker the new size. The guest daemon must
  then grow the file system in `Init` with the `EXT4_IOC_RESIZE_FS` ioctl on the mount point (the online
  grow that `resize2fs` uses; the sandbox image has no e2fsprogs).
- `generation` is unique on the node and increases with each new VM instance. It starts from the wall
  clock, so it also increases across agent restarts. It is the host-side boot ID of a VM instance
  (ENG-4606): every Create that makes a new VM (a snapshot restore) gets a new one. A repeated, idempotent
  Create returns the existing VM and its generation, so it is not a new boot. The guest's own
  `/proc/sys/kernel/random/boot_id` is the same in every clone of a template, so it is not an identity.
  The api_server passes the generation to the daemon's `Init` after each restore.

The agent serves the API on a Unix socket (`<data-dir>/run/host-agent.sock`, mode 0600, root only) and,
with `--listen`, on an mTLS TCP listener for the api_server (D2):

- `--tls-cert`, `--tls-key`: the agent's certificate and key (PEM files; Helm mounts them, ENG-4583).
- `--client-ca`: the api_server CA. The listener needs a client certificate that chains to it (TLS 1.3).
  A client with no certificate, or with one from another CA, fails the handshake.
- `--client-allowed-sans`: optional comma-separated DNS or URI SANs. If set, the client certificate must
  have one of them.
- The agent reads the three files again on the first handshake after one of them changes, so a rotated
  secret needs no restart. If the new files do not load (for example a half-written rotation), it keeps
  the last good ones.
- The agent does not start if `--listen` has no TLS files, or if TLS flags are set without `--listen`.
- Both listeners serve the same API.

`Dial(sandbox_id, guest_port, generation)` is a bidirectional stream of byte frames to a vsock port of a
running VM, for example the app preview (3010). Only the ports in `--dial-ports` (default `3010`) are
allowed (`PORT_NOT_ALLOWED`). Dial always refuses the guest daemon port (`--daemon-port`) with
`PORT_NOT_ALLOWED`, also if `--dial-ports` names it: use the pass-through. The agent does not start with
an empty `--dial-ports`. If nothing in the VM accepts the connection, the call fails with
`GUEST_UNREACHABLE`. A `generation` other than 0 must match the running VM, else the call fails with
`INSTANCE_MISMATCH`. A VM that is starting, stopping or exited fails with `VM_NOT_RUNNING`. One VM can
have at most `--dial-max-streams` open Dial streams (default 64); more fail with `DIAL_LIMIT`
(`RESOURCE_EXHAUSTED`). A failed write to the guest also ends the call with `GUEST_UNREACHABLE`. When the
client ends its send side, the agent keeps reading until the guest closes, because Firecracker turns a
host half-close into a full close.

### Guest daemon pass-through

The api_server calls the guest daemon (`craft.sandboxd.v1.Sandboxd`, `cmd/guest-daemon/`) with normal
gRPC stubs on the agent's listeners (the mTLS listener and the Unix socket). The agent forwards each
call to the daemon of one VM on vsock port `--daemon-port` (default 52). It never decodes the daemon
messages, so a new daemon call needs no agent change (`internal/server/passthrough.go`).

- Metadata `x-sandbox-id` (one lowercase UUID) names the VM. The agent removes it and forwards all other
  metadata, so `x-sandboxd-key` (the per-VM key) reaches the daemon. Headers, trailers and the
  daemon's status (domain `sandboxd.craft.onyx.app`) come back unchanged. The caller's deadline and
  cancel apply to the daemon call.
- Other services get `UNIMPLEMENTED`. A missing or bad `x-sandbox-id` is `INVALID_ARGUMENT`. No VM for
  the sandbox is `SANDBOX_NOT_FOUND`; a VM that is starting, stopping or exited is `VM_NOT_RUNNING`. If
  the daemon does not accept the vsock connection, the call fails with `GUEST_UNREACHABLE`. These errors
  have the agent's domain, so the client sees which side failed.
- The per-VM key: the api_server makes a new random key for each Create and sends it in `sandboxd_key`.
  The agent installs it with the daemon's `SetKey` before Create returns, so no other caller can set a
  key first. The daemon keeps the first key; every later call except `Health` must carry it, `Init`
  included. The pass-through refuses `SetKey` (`PERMISSION_DENIED`, `METHOD_NOT_ALLOWED`). The agent
  does not log the key or write it to the journal: after an agent restart the daemon still has it. If
  the daemon refuses the key (it has another one), Create fails with `GUEST_KEY_REJECTED`: stop that
  attempt and create a new one. If the daemon does not answer in time, Create fails with
  `GUEST_UNREACHABLE`; a repeat Create with the same attempt and key tries again. `Dial` refuses the
  daemon port, so a client cannot reach `SetKey` that way.
- The agent keeps one gRPC connection per VM instance (sandbox and generation) and shares it between
  calls. It closes the connection when the VM stops or exits; calls on it end with `VM_NOT_RUNNING`. An
  idle connection closes after 10 min and opens again on the next call.
- A message can be at most 16 MiB in each direction.
- After an agent restart, the first call opens a new connection. Commands in the VM keep running; a
  client re-attaches with `Stream(execution_id, offsets)`.

### Agent restart

While the agent restarts, new calls (including `Dial` and the egress relay) fail for a few seconds: 5.5 s
in the KVM restart test, about 7 s in T6. Open `Dial` streams and relay connections end with the old
process. VMs and their programs keep running; callers retry.

### How a VM starts

1. Admission: template, shape, scratch size, then memory (`MemAvailable >= mem_mib + --min-free-mem-mib`),
   disk (`--min-free-disk-gib`) and a free jailer UID. The full admission policy is ENG-4569.
   Firecracker checks nothing about a snapshot when it loads it. So before every restore the agent checks
   that the template key fits the node and that the files match their SHA256 (see Templates). Otherwise
   Create fails with `TEMPLATE_INCOMPATIBLE` and starts nothing.
2. The chroot `<data-dir>/jail/firecracker/<sandbox_id>/root/` gets a reflink copy of each template file,
   never a hard link: `snapshot/create` truncates its target in place, so a link would let one VM destroy
   the template. The read-only files (`rootfs.ext4`, `managed.ext4`, `upload-a.ext4`, `upload-b.ext4`,
   `vmstate`, `mem`) are root-owned, mode 0644. `scratch.ext4` is extended to `scratch_gib` and owned by
   the VM UID. After the copy, the agent checks that no template file changed since its hash check.
3. The agent runs
   `nsenter -t 1 -m -- systemd-run --scope --slice=fcvms.slice --unit=fcvm-<sandbox_id> -- jailer ... --new-pid-ns`.
   Each VM gets its own cgroup (the scope) in the host slice, outside the agent's container cgroup, so it
   survives an agent restart. The jailer gives it its own UID/GID (from `--uid-base`, `--uid-count`), a
   chroot and a PID namespace.
4. The agent checks the PID (`comm` is `firecracker`, the cgroup is the VM scope), restores the snapshot
   and resumes the VM.

Stop first removes everything that names the VM: its relay listener and identity, its relay
connections and its daemon pass-through connection. Only then does it send SIGKILL through a pidfd,
wait for the exit, stop the scope and remove the chroot (with the vsock socket), and then free the
jailer UID. A VM exit and a failed start use the same order. So a reused UID or socket path never
carries the old identity (ENG-4606). The api_server saves the session before it calls Stop. A VM that exits by itself shows as `EXITED`; its
files are removed at once.

If a cleanup fails, the VM shows as `EXITED` once its process is gone, and a repeat Stop retries the
cleanup. A newer attempt for that sandbox gets `VMM_FAILED` until a Stop succeeds. If a start fails and
the agent cannot confirm that the Firecracker process is gone, the agent keeps the chroot and does not
give the jailer UID to another VM.

### Journal and agent restart

VMs keep running when the agent stops. A new agent process re-adopts them from the journal,
`<data-dir>/journal/<sandbox_id>.json`: one JSON record per sandbox with the attempt, generation,
state, PID and PID start time, jailer UID, chroot, socket paths and template. Each write goes to a
temporary file, which is synced and renamed over the record; then the directory is synced.

| Record | Written | At start-up |
|---|---|---|
| `starting` | before the launch | Create never returned: remove the VM (if any) and the record. If the record keeps the stopped attempt that the start replaced, it becomes that tombstone again |
| `running` | after the launch, before Create returns | Adopt if the PID is still our Firecracker (same start time, comm, VM scope, `--id`) and `GET /` reports `Running`. Gone: `EXITED`. Same process but no API answer: adopt and log an error |
| `stopped` | after Stop | Tombstone (24 h): a repeat Stop succeeds, an old attempt gets `STALE_ATTEMPT` |

- A Firecracker process or chroot in the agent's layout with no record is an orphan. The agent kills it.
- If a record cannot be read, the agent logs it and leaves that VM alone. If the process scan fails, the
  agent removes nothing. It never kills on doubt.
- A sandbox is in doubt when the agent keeps its Firecracker running without a verified record: the
  record cannot be read, `Adopt` cannot verify the process, a live process belongs to a stopped or gone
  VM, or a failed start may have left the process running. The agent keeps the jailer UID of that
  process reserved (from `/proc/<pid>/status`). `Create` and `Stop` for the sandbox return
  `SANDBOX_IN_DOUBT`, and the agent does not change or remove its record.
- A doubt clears by itself: before `Create` or `Stop` returns `SANDBOX_IN_DOUBT`, the agent scans the
  processes again. If no Firecracker of the sandbox runs, the agent removes its leftover chroot, frees
  its UIDs and continues. An operator can also fix or remove the record and restart the agent, which
  then applies the rules above again (a VM with no record is an orphan and is killed).
- If the process scan fails at start-up, the UIDs of the kept VMs are not known. `Create` then returns
  `CAPACITY_VM_SLOTS` until a scan works.
- A failed tombstone write fails the Stop. The VM shows as `EXITED`, and a repeat Stop writes it again.
- The API serves only after recovery. While the agent restarts, new calls fail for a few seconds (5.5 s
  in the KVM test, 7 s in T6). VMs and their programs keep running.

### Egress relay

A VM has no network card. Its egress goes guest → vsock port 3128 → the agent relay
(`<chroot>/root/v.sock_3128`) → sandbox-proxy (`--egress-proxy`). Design: `plans/craft-fc-d1-egress-identity.md`
(D1-A). The proxy side is PR #17174 (`backend/onyx/sandbox_proxy/sandbox_identity/signed.py`).

- The relay reads one request head per connection, with strict parsing (no bare LF, no obs-fold, at most
  64 KiB). A bad head gets a 400 and never reaches the proxy.
- It removes every `Proxy-Authorization` and `X-Onyx-Session-Hint` from the VM, then adds
  `Proxy-Authorization: Bearer <token>`. The user name of a Basic `Proxy-Authorization` (the proxy URL
  userinfo) becomes `X-Onyx-Session-Hint`.
- A plain HTTP request (not CONNECT, not Upgrade) gets `Connection: close`: one signed request per
  connection.
- After the head, the relay streams both ways without buffering. When either side ends, both close
  (Firecracker vsock does not carry a half-close). The idle timeout is `--relay-idle-timeout` (default
  15 min; a value under 180 s becomes 180 s). Every VM connection gets its own proxy connection.
- One VM can have at most `--relay-max-conns` open relay connections (default 256). The relay closes a
  new connection over the cap at once, so one VM cannot use up the agent's memory or file descriptors.
  An accept error (for example `EMFILE`) does not stop the relay: it waits (5 ms, doubling up to 1 s)
  and accepts again.
- The token is an EdDSA JWT: header `{"alg":"EdDSA","typ":"JWT","kid"}`, claims `sub`
  (`spiffe://onyx/tenant/<tenant_id>/sandbox/<sandbox_id>`), `gen`, `node`, `iat`, `exp` (60 s), `jti`, `aud` (`sandbox-proxy`).
  `internal/relay/testdata/signed_identity_vectors.json` is a copy of the proxy's shared test vectors; a
  test fails if the two differ, or if the proxy file exists but cannot be read.
- The agent makes a new Ed25519 node key at each start (`kid` = `<node-id>-<unix time>-<8 random hex>`) and registers it
  with `PUT <--api-server-url>/microvm/node/signing-key` and
  `Authorization: Bearer $SANDBOX_NODE_REGISTRATION_SECRET`. It registers again every 20 min (the cache
  TTL is 1 h) and retries every 10 s after a failure.
- `CloseConnections(sandbox_id, attempt, generation)` closes every relay connection of the VM (T5 in
  `results/prebuild.md`); new connections still work. Stop and VM exit also close them. After an agent
  restart, the agent attaches the relay to each adopted VM again.

### Node requirements

- Linux, root, `/dev/kvm`, cgroup v2, systemd on the host.
- In a container: privileged and `hostPID`, with cgroup v2 mounted at `/sys/fs/cgroup` (the agent
  checks it). In a private cgroup namespace that mount shows the pod's own tree; the agent reads the
  host tree through `/proc/1/root/sys/fs/cgroup`.
- The agent works in the host cgroup namespace or in a pod's own one (ENG-4610). It compares its cgroup
  namespace with the one of PID 1 at start-up. In its own namespace, `/proc/<pid>/cgroup` of a VM reads
  `0::/../../fcvms.slice/fcvm-<id>.scope` (the number of `..` steps depends on the pod's cgroup). The
  agent then accepts a VM scope only if the host's `fcvms.slice/fcvm-<id>.scope/cgroup.procs`, read
  through `/proc/1/root/sys/fs/cgroup`, lists the PID. A read error is never a match, so the agent does
  not kill on doubt. If the host cgroup tree cannot be read, the agent does not start. An `nsenter
  --cgroup` wrapper is not needed. The agent does not `setns` itself: a cgroup namespace switch applies
  to one thread only, and Go runs on many threads.
- The data dir must be on XFS with reflink (the agent checks this at start-up). It must be mounted at
  the same path in the container and on the host, because the jailer runs in the host mount namespace.
  The path must be short enough for Unix socket paths (the agent checks this too).
- `--artifacts-dir` has `firecracker` and `jailer` v1.17.0 and the guest kernel `vmlinux` (the
  `onyxdotapp/craft-fc-artifacts` layout). The agent checks the binaries' SHA256 against `internal/binaries`
  and copies them to `<data-dir>/bin/<version>/`.
- `mkfs.ext4` (e2fsprogs) in the agent's container, for the template's empty drives.

### Templates

A template is `<data-dir>/templates/<version>/`. The agent builds it on the node from a root drive
(ENG-4566). Package `internal/template` reads and checks templates; `internal/tplbuild` builds them.

| File | Drive (guest device) | Content |
|---|---|---|
| `rootfs.ext4` | `rootfs` (`/dev/vda`, root, read-only) | the root drive from `build-rootfs.sh` |
| `scratch.ext4` | `scratch` (`/dev/vdb`) | empty ext4, `--template-scratch-gib`; never mounted in the template |
| `managed.ext4` | `managed` (`/dev/vdc`, read-only) | empty ext4 (8 MiB); the managed drive slot |
| `upload-a.ext4`, `upload-b.ext4` | `upload_a`, `upload_b` (`/dev/vdd`, `/dev/vde`, read-only) | 1 MiB placeholders for the later upload bundles; never mounted |
| `vmstate`, `mem` | | full snapshot |
| `manifest.json` | | see below |

Every file is root-owned, mode 0644, with one link.

#### Root drive input: where the rootfs build runs

`deployment/craft-fc/rootfs/build-rootfs.sh` needs Docker and the network (apt). The agent runs neither.
The agent takes the build output as files: `--rootfs-dir` is a directory with `rootfs.ext4` and
`manifest.json`. Put it on the data dir file system, so the copy into the template is a reflink.

The design for deployments (not built yet, see the open points in `plans/craft-fc-track-agent.md`):

- CI runs the rootfs build for each sandbox version and publishes the output as an image
  (`onyxdotapp/craft-fc-rootfs:<sandbox version>`, files only, like `craft-fc-artifacts`). An init
  container of the agent DaemonSet copies the two files into `<data-dir>/rootfs/`. An air-gapped install
  mirrors the image like every other image. The nodes need no Docker and no network.
- The egress CA is a build input, and each deployment has its own CA (sandbox-proxy makes it at first
  start). CI cannot add it. `build-rootfs.sh` must therefore split into a CI step (pull, apt, convert) and a
  CA step (add the CA, make the ext4) that the init container runs with the deployment CA (track C).
- With `--egress-ca`, the agent refuses a root drive whose CA fingerprint differs, and a template whose key
  has another CA. After a CA change, put a new root drive in `--rootfs-dir` and call `BuildTemplate`.

#### Build

At start-up (after recovery, while the API serves) and on `BuildTemplate`, the agent:

1. Reads `--rootfs-dir`. It checks that the root drive expects the drives `rootfs`, `scratch` (writable)
   and `managed` (read-only) in this order, and that its CA fits `--egress-ca`.
2. Computes the key and the template name: `<image tag>-<first 12 hex of the key hash>`, for example
   `v5.1.0-3fa91c0e7d22`. If a valid template with this name is there, it stops (and runs GC).
3. Copies the root drive into a staging directory (`<templates>/.build-<name>`) and checks its SHA256
   against the root drive manifest. It makes the empty scratch and managed drives (`mkfs.ext4`) and the
   upload slots.
4. Boots a VM in a jailer chroot (ID `tpl-<key hash[:12]>`, a UID from the pool) with the guest kernel,
   the boot args of the root drive manifest plus `craft.scratch=defer` (init does not mount scratch or
   managed), the five drives in the order above and the vsock (guest CID 3, `/v.sock`).
5. Waits until the guest daemon answers `Health` on vsock `--daemon-port`, pauses the VM and takes a full
   snapshot. It moves `vmstate` and `mem` into the staging directory and stops the VM.
6. Hashes the files, writes `manifest.json` and renames the staging directory to its name.
7. GC: keeps the `--template-keep` (default 2) newest templates and every template that a VM on the node
   uses (also starting and exited VMs). It removes the others, also templates with a manifest of an older
   layout. A staging directory left by an agent that stopped during a build is removed at start-up.

One build runs at a time; a `BuildTemplate` call during a build waits for it. A template that fails its
check is built again, unless a VM uses it.

Flags: `--rootfs-dir`, `--egress-ca`, `--template-vcpus` (2), `--template-mem-mib` (4096),
`--template-scratch-gib` (1), `--template-keep` (2), `--template-build-timeout` (5 min). The guest kernel
is `<artifacts-dir>/vmlinux`; the agent copies it to `<data-dir>/kernel/vmlinux-<sha256[:16]>`.

#### Manifest and checks

`manifest.json` (schema = layout version 2):

- `key`: `image_ref`, `image_digest`, `rootfs_sha256`, `rootfs_manifest_sha256`, `guest_kernel` (release),
  `guest_kernel_sha256`, `firecracker_version`, `cpu_model`, `host_kernel`, `ca_fingerprint`,
  `layout_version`, `boot_args`, `vcpus`, `mem_mib`, `scratch_gib`. The root drive is not byte-identical
  between builds, so the key has both its SHA256 and the SHA256 of its manifest.
- `key_sha256`: the SHA256 of the key.
- `files`: the SHA256 of each file.
- `snapshot_sha256`: a hash over the key hash and the file hashes, first `vmstate`, `mem` and `rootfs.ext4`.
- `built_at`, `build_ms`.

Before every restore, Create checks:

1. The manifest: the schema, `key_sha256` over the key, `snapshot_sha256` over the file hashes. An edited
   key or file hash fails here.
2. The key against the node: layout version, Firecracker version, CPU model, host kernel release, guest
   kernel SHA256 and (with `--egress-ca`) the CA. One mismatch is `TEMPLATE_INCOMPATIBLE` with the fields.
3. The files against `files`. The first check of a template after an agent start hashes every file (about
   8 GiB for a 4 GiB VM). The agent then keeps each file's fingerprint (inode, size, mtime, ctime). Later
   checks compare the fingerprints and hash again only if one changed. A changed file is
   `TEMPLATE_INCOMPATIBLE`.

`internal/kvmtest/helpers_test.go` (`buildTemplate`) uses the same pipeline for the older KVM tests.

## Generated code

Commit the generated code. Regenerate it after a change to the `.proto` file or the Firecracker version.

| Code | Generator |
|---|---|
| `proto/hostagent/v1/*.pb.go` | `protoc` 36.2, `protoc-gen-go` v1.36.12, `protoc-gen-go-grpc` v1.6.2 |
| `internal/fcapi/` | `go-swagger` v0.36.7, from the Firecracker v1.17.0 API spec |

```bash
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2
go install github.com/go-swagger/go-swagger/cmd/swagger@v0.36.7

# From this directory. protoc must find google/protobuf/timestamp.proto (the include/ dir of the protoc release).
protoc -I proto -I "$PROTOC_INCLUDE" \
  --go_out=paths=source_relative:proto --go-grpc_out=paths=source_relative:proto \
  proto/hostagent/v1/hostagent.proto

# The spec is src/firecracker/swagger/firecracker.yaml at the Firecracker release tag (Apache-2.0).
curl -fsSL -o internal/fcapi/firecracker-v1.17.0.yaml \
  https://raw.githubusercontent.com/firecracker-microvm/firecracker/v1.17.0/src/firecracker/swagger/firecracker.yaml
(cd internal/fcapi && rm -rf client models && swagger generate client -q -f firecracker-v1.17.0.yaml -A firecracker -t .)
go mod tidy
```

`firecracker-go-sdk` was not used: its newest code carries the v1.4.1 API spec, not v1.17.0.

## Tests

- Unit tests: `go test -race ./...`. They use a fake VMM and run in CI.
- KVM tests: build tag `kvm`, on a KVM host (not in CI yet; ENG-4561). They use the kit rootfs
  (`onyxdotapp/sandbox` + `fc-init` + the prototype guest agent `fc-agent.py`) and guest kernel 6.18.25.
  Host setup: `plans/craft-sandbox-bench/work-host-agent/` (AL2023 with kernel 6.18, `m8i.4xlarge`).

```bash
GOOS=linux GOARCH=amd64 go test -c -tags kvm -o hostagent-kvm.test ./internal/kvmtest
# On the host, as root. Defaults: KVM_DATA_DIR=/var/lib/craft-fc, KVM_IMG_DIR=/opt/craft-fc-test/img
# (vmlinux, rootfs.ext4, scratch-empty.ext4), KVM_ARTIFACTS_DIR=/opt/craft-fc, KVM_VMS=20.
./hostagent-kvm.test -test.v -test.run TestCoreKVM
# Agent restart: runs the agent binary (KVM_AGENT_BIN, default /opt/agent/host-agent) in a privileged
# --pid=host --cgroupns=host container (KVM_AGENT_IMAGE, default debian:trixie-slim) and restarts it.
./hostagent-kvm.test -test.v -test.run TestRestartKVM
# Egress: needs the proxy harness from plans/craft-sandbox-bench/work-host-agent/ (KVM_HARNESS_DIR,
# default /opt/harness), the PR #17174 backend (KVM_PR_BACKEND, default /opt/pr/backend), its Python env
# (KVM_PYTHON) and Docker for Redis.
./hostagent-kvm.test -test.v -test.run TestEgressKVM
# mTLS listener and Dial (test CAs from internal/testcerts).
./hostagent-kvm.test -test.v -test.run TestDialKVM
# Guest daemon pass-through, end to end: the agent binary in a --cgroupns=private container (KVM_CGROUPNS),
# a template from the deployment/craft-fc/rootfs root drive (KVM_IMG_DIR) booted with craft.scratch=defer,
# Init/Run/Start/Stream/Cancel over mTLS, egress through the proxy harness, agent restart, Stop order.
KVM_IMG_DIR=/opt/craft-fc-test/img3 ./hostagent-kvm.test -test.v -test.run TestPassthroughKVM
# Template pipeline (ENG-4566): the agent binary (KVM_AGENT_IMAGE needs e2fsprogs) builds from a
# build-rootfs.sh output (KVM_TB_ROOTFS) with --egress-ca (KVM_TB_CA); 20 restores with Init + Run, a
# tampered and a mismatched template, GC, agent restart.
KVM_TB_ROOTFS=/opt/tb/rootfs-out KVM_TB_CA=/opt/tb/ca/ca.crt ./hostagent-kvm.test -test.v -test.run TestTemplateBuildKVM
```

The KVM tests take the template version from the build (`KVM_TEMPLATE` is no longer used).

To check relay tokens against the proxy verifier on a dev machine:
`RELAY_TOKENS_OUT=/tmp/tokens.json go test -run TestWriteTokensForProxyVerifier ./internal/relay/`, then run
`verify_tokens.py` from the test kit with the backend Python env.
