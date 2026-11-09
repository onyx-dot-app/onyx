# microvm

Go module that runs Onyx Craft micro-VMs on Firecracker. Linear project P-ENG-224.

- `cmd/host-agent/`: the host agent. One process per Craft node. It runs the Firecracker VMs.
- `proto/hostagent/v1/`: the gRPC API of the host agent, with the generated Go code.
- `internal/`: the agent packages.
- The guest daemon (ENG-4571) will be `cmd/guest-daemon/` in this module.

Nothing deploys the agent yet. The Helm DaemonSet (ENG-4583) adds it behind `SANDBOX_RUNTIME=firecracker`.

## Host agent

### API

`proto/hostagent/v1/hostagent.proto`:

| Call | What it does |
|---|---|
| `Create(sandbox_id, attempt, template, vcpus, mem_mib, scratch_gib, tenant_id)` | Restores a VM from a template snapshot and returns it with its `generation`. A repeat call with the same `(sandbox_id, attempt)` returns the existing VM. A different attempt for a sandbox with a VM on the node returns `ATTEMPT_CONFLICT`. An attempt that is not newer than a stopped one returns `STALE_ATTEMPT`. |
| `Stop(sandbox_id, attempt, generation)` | Stops the VM only if all three match. A repeat Stop of the same instance succeeds with `already_stopped`. |
| `CloseConnections(sandbox_id, attempt, generation)` | Closes every relay connection of the VM. New connections still work. Stop and VM exit also close them. |
| `List()` | Every VM that the agent knows about, with its state (`STARTING`, `RUNNING`, `EXITED`). |
| `NodeInfo()` | Total and free memory, free disk, VM count, templates on disk, CPU model, Firecracker, host kernel and guest kernel versions. |
| `CloseConnections(sandbox_id, attempt, generation)` | Closes the VM's egress relay connections (see Egress relay). |
| `Dial(sandbox_id, guest_port, generation)` | Byte stream to a guest vsock port (see below). |

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
- `generation` is unique on the node and increases with each Create. It starts from the wall clock, so it
  also increases across agent restarts.

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
running VM: the guest daemon port or the app preview (3010). Only the ports in `--dial-ports` (default
`52,3010`; 52 is the prototype daemon port until ENG-4571 fixes the daemon port) are allowed
(`PORT_NOT_ALLOWED`). The agent does not start with an empty `--dial-ports`. If nothing in the VM
accepts the connection, the call fails with `GUEST_UNREACHABLE`. A `generation` other than 0 must match
the running VM, else the call fails with `INSTANCE_MISMATCH`. One VM can have at most
`--dial-max-streams` open Dial streams (default 64); more fail with `DIAL_LIMIT` (`RESOURCE_EXHAUSTED`).
A failed write to the guest also ends the call with `GUEST_UNREACHABLE`. When the client ends its send
side, the agent keeps reading until the guest closes, because Firecracker turns a host half-close into a
full close.

While the agent restarts, new calls (including `Dial` and the egress relay) fail for a few seconds: 5.5 s
in the KVM restart test, about 7 s in T6. Open `Dial` streams and relay connections end with the old
process. VMs and their programs keep running; callers retry.

### How a VM starts

1. Admission: template, shape, scratch size, then memory (`MemAvailable >= mem_mib + --min-free-mem-mib`),
   disk (`--min-free-disk-gib`) and a free jailer UID. The full admission policy is ENG-4569.
2. The chroot `<data-dir>/jail/firecracker/<sandbox_id>/root/` gets hard links to the template's
   `rootfs.ext4`, `vmstate` and `mem` (shared, read-only, root-owned) and a reflink copy of `scratch.ext4`,
   extended to `scratch_gib` and owned by the VM UID.
3. The agent runs
   `nsenter -t 1 -m -- systemd-run --scope --slice=fcvms.slice --unit=fcvm-<sandbox_id> -- jailer ... --new-pid-ns`.
   Each VM gets its own cgroup (the scope) in the host slice, outside the agent's container cgroup, so it
   survives an agent restart. The jailer gives it its own UID/GID (from `--uid-base`, `--uid-count`), a
   chroot and a PID namespace.
4. The agent checks the PID (`comm` is `firecracker`, the cgroup is the VM scope), restores the snapshot
   and resumes the VM.

Stop sends SIGKILL through a pidfd, waits for the exit, stops the scope and removes the chroot. The
api_server saves the session before it calls Stop. A VM that exits by itself shows as `EXITED`; its
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
  with `PUT <--api-server-url>/build/sandbox-node/signing-key` and
  `Authorization: Bearer $SANDBOX_NODE_REGISTRATION_SECRET`. It registers again every 20 min (the cache
  TTL is 1 h) and retries every 10 s after a failure.
- `CloseConnections(sandbox_id, attempt, generation)` closes every relay connection of the VM (T5 in
  `results/prebuild.md`); new connections still work. Stop and VM exit also close them. After an agent
  restart, the agent attaches the relay to each adopted VM again.

### Node requirements

- Linux, root, `/dev/kvm`, cgroup v2, systemd on the host.
- In a container: privileged, `hostPID`, and the host `/sys/fs/cgroup`.
- The data dir must be on XFS with reflink (the agent checks this at start-up). It must be mounted at
  the same path in the container and on the host, because the jailer runs in the host mount namespace.
  The path must be short enough for Unix socket paths (the agent checks this too).
- `--artifacts-dir` has `firecracker` and `jailer` v1.17.0 (the `onyxdotapp/craft-fc-artifacts` layout).
  The agent checks their SHA256 against `internal/binaries` and copies them to `<data-dir>/bin/<version>/`.

### Templates

A template is `<data-dir>/templates/<version>/` with `manifest.json`, `rootfs.ext4`, `scratch.ext4`,
`vmstate` and `mem`. The template pipeline (ENG-4566) must:

- take the snapshot inside a jailer chroot, so that the drive paths are `/rootfs.ext4` (drive `rootfs`)
  and `/scratch.ext4` (drive `scratch`), and the vsock is guest CID 3 with UDS `/v.sock`;
- make every file root-owned and mode 0644;
- write `manifest.json`: `version`, `vcpus`, `mem_mib`, `scratch_gib`, `guest_kernel`,
  `firecracker_version`.

`internal/kvmtest/helpers_test.go` (`buildTemplate`) is a test version of this.

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
```

To check relay tokens against the proxy verifier on a dev machine:
`RELAY_TOKENS_OUT=/tmp/tokens.json go test -run TestWriteTokensForProxyVerifier ./internal/relay/`, then run
`verify_tokens.py` from the test kit with the backend Python env.
