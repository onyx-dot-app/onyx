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
| `Create(sandbox_id, attempt, template, vcpus, mem_mib, scratch_gib, tenant_id, sandboxd_key)` | Restores a VM from a template snapshot and returns it with its `generation`. With `sandboxd_key`, it installs that key in the guest daemon (`SetKey` over vsock, up to 10 s) before it returns a running VM (see Guest daemon pass-through). `SetKey` also carries the deployment egress CA (see Root drive input); without a readable CA, Create fails with `EGRESS_CA_UNAVAILABLE` before any VM starts. A repeat call with the same `(sandbox_id, attempt)` returns the existing VM. A different attempt for a sandbox with a VM on the node returns `ATTEMPT_CONFLICT`. An attempt that is not newer than a stopped one returns `STALE_ATTEMPT`. |
| `Stop(sandbox_id, attempt, generation)` | Stops the VM only if all three match. A repeat Stop of the same instance succeeds with `already_stopped`. |
| `CloseConnections(sandbox_id, attempt, generation)` | Closes every relay connection of the VM. New connections still work. Stop and VM exit also close them. |
| `List()` | Every VM that the agent knows about, with its state (`STARTING`, `RUNNING`, `EXITED`). |
| `NodeInfo()` | Total and free memory, the memory reserve and the memory of starting VMs, free disk, VM count, the drain state, templates on disk (with their key, `compatible` and `balloon`), CPU model, Firecracker, host kernel and guest kernel versions. |
| `SetDrain(drain)` | Sets or clears the manual drain flag (see Memory, admission and drain). |
| `BuildTemplate()` | Builds the node's template from `--rootfs-dir` if no valid one for its key is there, then removes old templates (see Templates). |
| `PutManagedImage(stream: header{sha256, size_bytes}, data...)` | Uploads a managed bundle (a zip) and builds its read-only ext4 image on the node (see Managed drive). |
| `SwapManaged(image_id, targets[{sandbox_id, attempt, generation, sandboxd_key}])` | Puts a managed image into running VMs, one VM at a time, without a restart (see Managed drive). One result per target. |
| `CloseConnections(sandbox_id, attempt, generation)` | Closes the VM's egress relay connections (see Egress relay). |
| `Dial(sandbox_id, guest_port, generation)` | Byte stream to a guest vsock port (see below). |
| `craft.sandboxd.v1.Sandboxd/*` | Any guest daemon call, forwarded to the VM named by `x-sandbox-id` (see Guest daemon pass-through). |
| `CaptureSession(sandbox_id, attempt, generation, sandboxd_key, session_id, ...)` | Calls the daemon's `CaptureSession` and spools the archive on the node. Returns `capture_id`, `size_bytes` and `sha256` (see Session saves). |
| `UploadCapture(capture_id, request)` | Sends a spooled capture with a presigned PUT. Deletes the spool on success. |
| `DiscardCapture(capture_id)` | Deletes a spooled capture. |
| `RestoreSession(sandbox_id, attempt, generation, sandboxd_key, session_id, request, size_bytes, sha256, ...)` | Streams a presigned GET into the daemon's `RestoreSession`. |

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
- `--advertise-address`: the `host:port` that the api_server dials for this listener. The agent sends it
  as `agent_address` with the node key registration (below). Default: `$POD_IP` with the `--listen`
  port (IPv6 in brackets), or the `--listen` host if it is a specific address. The host must be an IP
  address or a DNS name of letters, digits, `.` and `-`; the api_server accepts the same hosts. If there is no address, the registration has
  no `agent_address` and the api_server cannot place VMs on the node. The agent does not start if
  `--advertise-address` is set without `--listen`.
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
- A message can be at most 16 MiB in each direction. The vsock connection uses 16 MiB HTTP/2 windows.
- After an agent restart, the first call opens a new connection. Commands in the VM keep running; a
  client re-attaches with `Stream(execution_id, offsets)`.

### Session saves

The agent moves session archives between the guest daemon and object storage. The api_server
signs each request for one object and one method (FileStore `presign_upload` / `presign_download`). The
agent sends it with exactly the signed headers. It has no storage credentials, and the guest never sees
a URL (`internal/server/saves.go`, `internal/transfer`).

- Each call names the VM instance (`sandbox_id`, `attempt`, `generation`; `INSTANCE_MISMATCH` otherwise)
  and sends the guest daemon key again: the agent does not keep it. Daemon errors pass through with the
  daemon's domain (for example `LIMIT_EXCEEDED`, `FILE_NOT_FOUND`).
- `CaptureSession` spools the daemon's tar + zstd stream to `<data-dir>/captures/<capture_id>`. It
  reserves `--capture-max-bytes` (default 1 GiB) of disk first and keeps `--min-free-disk-gib` free
  (`CAPACITY_DISK`). A larger archive fails with `CAPTURE_TOO_LARGE`. The response has the size and the
  SHA-256 that `presign_upload` needs. A spool that is not uploaded is deleted after `--capture-ttl`
  (default 15 min); the agent also deletes all spools at start.
- `UploadCapture` fails with `ARCHIVE_MISMATCH` if the signed `Content-Length` is not the spool size, and
  with `TRANSFER_FAILED` on a network error or a non-2xx status. The spool stays for a retry with a new
  URL. On success the agent deletes it. `CAPTURE_NOT_FOUND`: capture again.
- `RestoreSession` downloads with `--transfer-parallel` (default 8, 1 to 64) range GETs of
  `--transfer-part-bytes` (default 8 MiB, 1 MiB to 256 MiB; other values stop the agent at start-up) at once, in order, and streams the bytes into the daemon in 1 MiB messages while it
  hashes them. One S3 stream gives about 100 MB/s; 8 ranges made the 1 GiB restore 9.3 s → 5.7 s (KVM).
  A restore holds at most `--transfer-parallel` + 1 parts in memory. The daemon
  extracts into a staging directory and replaces the session's capture roots only after the size and
  SHA-256 match. A mismatch is `ARCHIVE_MISMATCH` (agent) or `ARCHIVE_INVALID` (daemon); the session
  does not change.
- URLs and redirect targets must be `https`, unless `--transfer-allow-http` (a test object store).
  `--transfer-timeout` (default 10 min) bounds one upload or one single-GET restore. A ranged restore
  uses one timeout for the whole download (all parts, queued parts included), so set it for the
  longest expected restore. Errors and logs show the URL without its query string.
- Order for the api_server: `CaptureSession` → `presign_upload(size_bytes, sha256)` → `UploadCapture` →
  `finalize_presigned_upload` → commit the new archive → only then delete old archives.

### Agent restart

While the agent restarts, new calls (including `Dial` and the egress relay) fail for a few seconds: 5.5 s
in the KVM restart test, about 7 s in T6. Open `Dial` streams and relay connections end with the old
process. VMs and their programs keep running; callers retry.

### How a VM starts

1. Admission: drain, template, shape, scratch size, disk (`--min-free-disk-gib`), memory and a free
   jailer UID (see Memory, admission and drain). Firecracker checks nothing about a snapshot when it loads it. So before every restore the agent checks
   that the template key fits the node and that the files match their SHA256 (see Templates). Otherwise
   Create fails with `TEMPLATE_INCOMPATIBLE` and starts nothing.
2. The chroot `<data-dir>/jail/firecracker/<sandbox_id>/root/` gets a reflink copy of each template file,
   never a hard link: `snapshot/create` truncates its target in place, so a link would let one VM destroy
   the template. The read-only files (`rootfs.ext4`, `managed.ext4`, `upload-a.ext4`, `upload-b.ext4`,
   `managed-b.ext4`, `vmstate`, `mem`) are root-owned, mode 0644. `scratch.ext4` is extended to `scratch_gib` and owned by
   the VM UID. After the copy, the agent checks that no template file changed since its hash check.
3. The agent runs
   `nsenter -t 1 -m -- systemd-run --scope --slice=fcvms.slice --unit=fcvm-<sandbox_id> --property=MemoryMax=... --property=CPUQuota=... -- jailer ... --new-pid-ns`.
   Each VM gets its own cgroup (the scope) in the host slice, outside the agent's container cgroup, so it
   survives an agent restart. The scope has `memory.max` = guest memory + `--vm-mem-overhead-mib` and
   `cpu.max` = one CPU per vCPU (see Memory, admission and drain). The jailer gives it its own UID/GID (from `--uid-base`, `--uid-count`), a
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
the agent cannot confirm that the Firecracker process is gone, Create returns `SANDBOX_IN_DOUBT`, and
the agent keeps the chroot and does not give the jailer UID to another VM. An unreadable memory or
disk statistic refuses Create with `CAPACITY_MEMORY` or `CAPACITY_DISK`.

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

A `running` record also has `managed`: the number of managed slots, the active slot (`a` or `b`), the
image behind each slot, and `pending` while a swap runs (see Managed drive). A record without `managed`
(written before ENG-4614) means one slot.

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
  TTL is 1 h) and retries every 10 s after a failure. The body is `node_id`, `key_id`, `public_key` and,
  with an advertise address, `agent_address`. The api_server keeps the address as long as the key. A
  registration without `agent_address` clears the address the node registered before.
- `CloseConnections(sandbox_id, attempt, generation)` closes every relay connection of the VM (T5 in
  `results/prebuild.md`); new connections still work. Stop and VM exit also close them. After an agent
  restart, the agent attaches the relay to each adopted VM again.

### Node state report

The agent pushes its full VM state to the api_server; the api_server reconciles the node's placement
records on each report (`backend/onyx/microvm/node_report.py`). The agent pushes reports instead of
the api_server polling nodes, because Onyx has no scheduler inside the api_server (see Sandbox state
model).
Placement does not depend on reports: it asks the agent with `List`.

- After the first successful key registration, and then every `--state-report-interval` (default 20 s,
  `0` turns it off), the agent sends `POST <--api-server-url>/microvm/node/state` with `node_id`,
  `vms` and `ended`:
  - `vms`: one entry per VM of `List` (`sandbox_id`, `tenant_id`, `attempt`, `generation`, `state`,
    `template`, `vcpus`, `mem_mib`, `scratch_gib`, `pid`, `started_at`).
  - `ended`: each VM instance that exited (`reason` `EXITED`) or stopped (`STOPPED`) within
    `--ended-retention` (default 10 min, `0` = none), with `sandbox_id`, `tenant_id`, `attempt`,
    `generation`, `ended_at`. Every report in that window lists it again, so a missed report changes
    nothing. The list is in memory only.
- `Authorization: Bearer <token>`: an EdDSA JWT signed with the registered node key. Header `kid` = the
  registered key id. Claims `node`, `iat`, `exp` (60 s), `jti` (single use), `aud`
  (`onyx-api-server-node-report`, never `sandbox-proxy`) and `body_sha256` (hex SHA-256 of the body).
  The registration secret is not sent.
- At most 1024 VMs and 1 MiB. A larger report is not sent, because a cut list would make the api_server
  clear live records. Over 1024 ended entries, the oldest are left out. The api_server applies the same
  caps.
- A failed report is logged. The next one waits twice as long, up to 2 min, then the interval again.
- The api_server answers `409` while the node has no registered `agent_address`: it needs the address to
  check a VM again before it clears a record.
- Placement records have no TTL. A record goes away only on Stop, on a discard, or when a report shows
  that its VM ended or is gone (after a fresh `List` under the sandbox lock). The api_server stops VMs
  of an older attempt on that report, and VMs that it does not know after a grace period. It adopts a
  VM that a reservation names only when the guest daemon accepts the attempt's key: Health shows that
  the guest answers, then a repeat Create installs the key or is rejected when the guest holds another
  key. Adoptions run after the orphan stops. A pending key install waits 60 s before the next try. A
  reserved VM whose key is lost or rejected, or whose guest did not answer for 10 min (and fails one
  more Health), is stopped after the grace period.
- The api_server records the time of each accepted report. A node counts as dead when its registration
  expired, or when it reported before but not within `SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS` (default
  60 s, three intervals; `0` turns this off). Wake then starts the next attempt on a live node.

### Sandbox state model

The agent runs the VMs; the api_server makes sure that each sandbox has at most one VM.

| Rule | Onyx |
|---|---|
| Durable record, no TTL | Placement record (node, attempt, generation, last activity) in the tenant cache, no TTL. Only Stop, a discard, or a report that shows the VM ended or gone (after a fresh `List` under the sandbox lock) removes it. |
| One VM per sandbox: reservation before Create | Reservation (attempt, node), SET NX or compare-and-set, no TTL. A Create with no known outcome keeps it, so the next wake repeats the same Create on the same node. A reservation on a dead node is taken over with the next attempt. |
| Request-path ensure | Wake (`place_sandbox_vm`) reads the record and asks that node's agent with `List`. A running VM is returned; otherwise wake starts the next attempt. It never waits for a report. |
| Instance fence | (attempt, generation) fence: `CacheBackend.replace_if_value` / `delete_if_value` (Redis and Postgres). A write for an older instance never replaces a newer record. |
| Node state push | The agent pushes its list every 20 s (Node state report), because Onyx has no scheduler inside the api_server to poll nodes. |
| Ended list | The agent lists each exited or stopped VM for `--ended-retention` (10 min). |
| Orphan stops | The api_server stops a VM of an older attempt at once, and an unknown VM after `SANDBOX_FC_ORPHAN_GRACE_SECONDS` (40 s), at most 8 per report, with no checkpoint. |
| API-side idle evictor | Idle evictor on the record's last activity (`SANDBOX_FC_IDLE_TIMEOUT_SECONDS`). The stop waits for session saves (ENG-4580). |
| Dead node | Dead node (registration expired, or no report within `SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS`): records stay; wake starts the next attempt on a live node, and the old VM is an orphan if it reports again. |

Keys without a TTL need a Redis eviction policy that never evicts them (`volatile-*` or `noeviction`), or the
Postgres cache backend. The chart's bundled Redis uses `allkeys-lru`.

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
- `mkfs.ext4` (e2fsprogs) in the agent's container, for the template's empty drives and the managed
  images (`mkfs.ext4 -d`). The agent image (ENG-4607) must install e2fsprogs.
- Privileged enough to mount a tmpfs in its own mount namespace (the managed bundle stage).

### Metrics, guest logs and audit

- **Metrics (ENG-4570).** `--metrics-listen` (for example `:9464`, default off) serves Prometheus
  `/metrics` over plain HTTP. Auth is the same as the api_server `/metrics`
  (`backend/onyx/server/metrics/metrics_auth.py`): scrapers send `Authorization: Bearer <token>`, where
  `--metrics-token-file` holds the Onyx `METRICS_AUTH_TOKEN`. The agent reads the file on each scrape,
  so a rotated Secret applies without a restart. With no token (no flag, or a missing or empty file)
  every scrape gets 401. `--metrics-auth-disabled` (like `DISABLE_METRICS_AUTH=true`) removes auth. The VM table, node memory, allocated memory, open relay
  connections and open Dial streams are read at scrape time, in one pass (observable gauges). No metric
  has a sandbox or tenant label.

  | Metric | Type | Labels |
  |---|---|---|
  | `craft_fc_host_agent_create_duration_seconds` | histogram | `result`: created, existing, refused, failed |
  | `craft_fc_host_agent_admissions_total` | counter | `result`: admitted, refused (stopped before admission passed), failed (the start failed after admission); `reason`: ErrorReason |
  | `craft_fc_host_agent_vms` | gauge | `state`: starting, running, exited |
  | `craft_fc_host_agent_vm_memory_allocated_bytes`, `_vm_vcpus_allocated` | gauge | |
  | `craft_fc_host_agent_node_memory_total_bytes`, `_node_memory_available_bytes`, `_node_disk_free_bytes` | gauge | |
  | `craft_fc_host_agent_node_stats_errors` | gauge | `stat`: memory, disk |
  | `craft_fc_host_agent_rpc_requests_total` | counter | `method` (HostAgent method, else `unknown`), `code` (gRPC) |
  | `craft_fc_host_agent_rpc_duration_seconds` | histogram | `method` |
  | `craft_fc_host_agent_passthrough_calls_total` | counter | `method` (daemon method, else `unknown`), `code` |
  | `craft_fc_host_agent_relay_open_connections` | gauge | |
  | `craft_fc_host_agent_relay_connections_total` | counter | `result`: accepted, over_cap, upstream_failed |
  | `craft_fc_host_agent_dial_open_streams` | gauge | |
  | `craft_fc_host_agent_guest_log_bytes_total`, `_guest_log_dropped_bytes_total` | counter | `stream`: console, firecracker |

  The Go runtime and process collectors are on the same registry.
- **Guest logs.** The agent tails each VM's serial console (`console.log`, Firecracker's stdout and
  stderr) and Firecracker log (`fc.log`) and writes one JSON line per log line to its **stdout**:
  `kind=guest_log`, `stream`, `sandbox_id`, `generation`, `tenant_id`, `line`. The agent's own log and
  the audit lines go to stderr. One goroutine reads all VMs every second. Each VM may ship
  `--guest-log-rate` bytes/s (default 16 KiB/s, burst `--guest-log-burst`, default 256 KiB), and the
  node `--guest-log-node-rate` (default 1 MiB/s, burst 4 s). Bytes over a budget are skipped, counted in
  `guest_log_dropped_bytes_total`, and reported in one `guest log rate limit` line. Lines over 4 KiB are
  cut (`truncated=true`). Stop and VM exit ship the last lines before the files are removed, also for a
  VM that ended before its first read. After an agent restart, adopted VMs are read from the current end
  of their files, so nothing is shipped twice.
  `--guest-log-rate=0` turns shipping off.
- **Log files on disk.** `--guest-log-max-file-bytes` (default 16 MiB, 0 = no cap) caps each file, also
  with shipping off. Firecracker writes the console to its stdout, which the agent opens with `O_APPEND`,
  so after the shipper has read past the cap it empties `console.log` in place and starts again at 0.
  If bytes arrived after the last read, it waits for the next read, unless the file is over twice the
  cap; then the unread bytes are dropped and counted. Firecracker v1.17 opens `fc.log` without
  `O_APPEND` (a truncate would leave it writing at its old offset), so for `fc.log` the agent punches a
  hole over the bytes it has read (`fallocate` `PUNCH_HOLE`, Linux): the size stays and the disk blocks
  are freed. A failed truncate or hole punch logs one `guest log cap failed` error line (with the path)
  until the cap works again.
- **Audit.** One `rpc` line (`kind=audit`) on stderr for every HostAgent call and every daemon
  pass-through call: `method`, `passthrough`, `caller` (the URI and DNS SANs of the verified client
  certificate, or `unix` for the root-only socket), `sandbox_id`, `tenant_id` (from the request or the VM
  table), `attempt` and `generation` when the request has them, `result` (gRPC code), `reason`
  (ErrorReason) and `ms`. A gRPC interceptor writes it. It never reads request or response bodies past
  the IDs, and never logs metadata, so `sandboxd_key` and `x-sandboxd-key` never reach the log.

### Templates

A template is `<data-dir>/templates/<version>/`. The agent builds it on the node from a root drive
(ENG-4566). Package `internal/template` reads and checks templates; `internal/tplbuild` builds them.

| File | Drive (guest device) | Content |
|---|---|---|
| `rootfs.ext4` | `rootfs` (`/dev/vda`, root, read-only) | the root drive from `build-rootfs.sh` |
| `scratch.ext4` | `scratch` (`/dev/vdb`) | empty ext4, `--template-scratch-gib`; never mounted in the template |
| `managed.ext4` | `managed` (`/dev/vdc`, read-only) | empty ext4 (8 MiB); the managed drive slot |
| `upload-a.ext4`, `upload-b.ext4` | `upload_a`, `upload_b` (`/dev/vdd`, `/dev/vde`, read-only) | 1 MiB placeholders for the later upload bundles; never mounted |
| `managed-b.ext4` | `managed_b` (`/dev/vdf`, read-only; layout 3) | 1 MiB placeholder: managed slot B, the spare for a swap; never mounted in the template |
| `vmstate`, `mem` | | full snapshot |
| `manifest.json` | | see below |

Every file is root-owned, mode 0644, with one link.

#### Root drive input: where the rootfs build runs

`deployment/craft-fc/rootfs/build-rootfs.sh` needs Docker and the network (apt). The agent runs neither.
The agent takes the build output as files: `--rootfs-dir` is a directory with `rootfs.ext4` and
`manifest.json`. Put it on the data dir file system, so the copy into the template is a reflink.

Delivery (ENG-4648, `deployment/craft-fc/rootfs/README.md`):

- CI converts `onyxdotapp/craft-runtime:<tag>` with no egress CA and publishes the output as
  `onyxdotapp/craft-fc-artifacts:rootfs-<version>` (files only). An init container of the agent DaemonSet
  copies the two files into `<data-dir>/rootfs/` (Helm `craft.hostAgent.rootfs`). An air-gapped install
  mirrors the image like every other image. The nodes need no Docker and no network.
- Each deployment has its own egress CA (sandbox-proxy makes it at first start). The agent reads it at each
  Create (30 s cache) from `--egress-ca-configmap <namespace>/<name>[:<key>]` (the sandbox-proxy ConfigMap,
  through the Kubernetes API) or `--egress-ca <file>`, and sends it with `SetKey`. The guest daemon installs
  it at `Init`. A CA change needs no new root drive and no new template.
- One CA read runs at a time (5 s timeout). Callers with a CA do not wait for it. When reads fail, Create
  uses the last good CA for up to 1 h after its read, and the agent waits 5 s before the next read.
- The daemon writes the bundle before the anchor (`craft-egress-ca.crt`). Until the bundle no longer
  has the old CA, the anchor names it, so a retry after a failed write still removes it.
- A root drive with no CA has an empty CA in the template key, so it fits every deployment. A drive built
  with `--ca` (older builds) must have the deployment CA: the agent refuses it, and a template whose key
  has another CA, if the CA it read at start differs. An agent with no CA source refuses a root drive
  and a template with no CA (TEMPLATE_INCOMPATIBLE): their VMs would trust no egress CA.

#### Build

At start-up (after recovery, while the API serves) and on `BuildTemplate`, the agent:

1. Reads `--rootfs-dir`. It checks that the root drive expects the drives `rootfs`, `scratch` (writable)
   and `managed` (read-only) in this order, that its `managed_slots` (if any) are `a=/dev/vdc` and
   `b=/dev/vdf`, and that its CA (if it has one) fits the deployment CA.
2. Computes the key and the template name: `<image tag>-<first 12 hex of the key hash>`, for example
   `v5.1.0-3fa91c0e7d22`. If a valid template with this name is there, it stops (and runs GC).
3. Copies the root drive into a staging directory (`<templates>/.build-<name>`) and checks its SHA256
   against the root drive manifest. It makes the empty scratch and managed drives (`mkfs.ext4`), the
   upload slots and managed slot B.
4. Boots a VM in a jailer chroot (ID `tpl-<key hash[:12]>`, a UID from the pool) with the guest kernel,
   the boot args of the root drive manifest plus `craft.scratch=defer` (init does not mount scratch or
   managed), the six drives in the order above and the vsock (guest CID 3, `/v.sock`).
5. Waits until the guest daemon answers `Health` on vsock `--daemon-port`, pauses the VM and takes a full
   snapshot. It moves `vmstate` and `mem` into the staging directory and stops the VM.
6. Hashes the files, writes `manifest.json` and renames the staging directory to its name.
7. GC: keeps the `--template-keep` (default 2) newest templates and every template that a VM on the node
   uses (also starting and exited VMs). It removes the others, also templates with a manifest that the
   agent cannot read. A staging directory left by an agent that stopped during a build is removed at start-up.

One build runs at a time; a `BuildTemplate` call during a build waits for it. A template that fails its
check is built again, unless a VM uses it.

Flags: `--rootfs-dir`, `--egress-ca` or `--egress-ca-configmap`, `--template-vcpus` (2), `--template-mem-mib` (4096),
`--template-scratch-gib` (1), `--template-keep` (2), `--template-build-timeout` (5 min). The guest kernel
is `<artifacts-dir>/vmlinux`; the agent copies it to `<data-dir>/kernel/vmlinux-<sha256[:16]>`.

#### Manifest and checks

`manifest.json` (schema = layout version, 4 for new builds):

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
   kernel SHA256 and (for a template whose root drive has a CA) the CA. One mismatch is `TEMPLATE_INCOMPATIBLE` with the fields.
3. The files against `files`. The first check of a template after an agent start hashes every file (about
   8 GiB for a 4 GiB VM). The agent then keeps each file's fingerprint (inode, size, mtime, ctime). Later
   checks compare the fingerprints and hash again only if one changed. A changed file is
   `TEMPLATE_INCOMPATIBLE`.

Layouts: the agent builds layout 4 and still restores layouts 2 and 3.

- Layout 4 (ENG-4569): the drives of layout 3, plus the balloon device (see Memory, admission and drain).
  Firecracker accepts a balloon only before boot, and a restore keeps it, so the template VM has it.
  `TemplateInfo.balloon` is true.
- Layout 3: six drives, managed slot B last, so the older drives keep their guest devices. No balloon: its
  VMs never give free memory back to the node.
- Layout 2: five drives. Its VMs cannot swap the managed drive (`MANAGED_SWAP_UNSUPPORTED`).
  `TemplateInfo.managed_slots` says which one a template is.

`internal/kvmtest/helpers_test.go` (`buildTemplate`) uses the same pipeline for the older KVM tests.

### Memory, admission and drain (ENG-4569)

Results: `plans/craft-sandbox-bench/results/mem.md` (decision test) and `results/mem-admission.md`.

**Balloon.** Layout 4 templates boot with the Firecracker balloon: `amount_mib` 0, `deflate_on_oom`,
statistics every 5 s, free page reporting on, free page hinting off (a developer preview with a memory
corruption race). The balloon never inflates: a guest that works against an inflated balloon is many
times slower. Free page reporting gives the pages that the guest frees back to the node.

**Guest side** (guest daemon flags, `cmd/guest-daemon/README.md`):

- At start the daemon sets the page reporting order to 0 (`--page-reporting-order`). The kernel default
  (9) reports only free 2 MiB blocks and returns about half of the free memory. The template snapshot
  keeps the setting, so every restore has it.
- After `--reclaim-idle` (default 5 min) with no daemon call (Health does not count), the daemon drops
  the page cache and compacts memory, once per idle period. Reporting then returns those pages too.

**Cgroup limits.** Each VM scope has `memory.max` = `mem_mib` + `--vm-mem-overhead-mib` (default 128) and
`cpu.max` = `vcpus` CPUs. The scope also counts the host page cache of the VM's drive and memory files;
the kernel reclaims it at the limit. A guest cannot use more than its memory, so a guest memory hog meets
the guest's own OOM killer first in the KVM test (also with a 16 MiB overhead). That test covers one
workload; it does not prove every VM shape. If guest memory plus the host memory that the scope counts
(Firecracker, page cache) reaches `memory.max` first, the cgroup OOM killer kills Firecracker before the
guest OOM killer acts. Keep the default overhead unless a test of the VM shape shows a smaller one is
safe. A Firecracker that grows past the limit is OOM-killed; the kernel kills that VM only, and the agent
shows it as `EXITED` and cleans it up. `io.max` is not set.

**Admission.** Create needs `MemAvailable` (measured, `/proc/meminfo`) >= guest memory of the VMs that are
starting + `mem_mib` + `--min-free-mem-mib` (default 2048). Starting VMs count at their full size because
their memory is not in use yet; running VMs count at what they use, because the balloon returns what the
guests free. The check runs under the agent lock, so two Creates never take the same memory. A refusal is
`CAPACITY_MEMORY` with the numbers in the message and in `ErrorInfo.metadata`: `mem_total_mib`,
`mem_available_mib`, `mem_needed_mib`, `vm_mem_mib`, `mem_starting_mib`, `mem_reserve_mib`. `NodeInfo`
returns `mem_reserve_mib` and `mem_starting_mib`.

**Drain.** The node drains while the manual flag is set (`SetDrain`, kept in `<data-dir>/drain.json`
across restarts) or while its Node has a taint from `--drain-taints` (default
`node.kubernetes.io/unschedulable`, which `kubectl cordon` and `kubectl drain` set). With
`--watch-node-drain`, the agent reads its own Node (`--node-id`, from `$NODE_NAME`) every
`--drain-poll-interval` (default 10 s) with the pod's ServiceAccount (RBAC: `get` on nodes). The first read
runs before the API serves. If a read fails, the agent keeps the last taints and shows the error in
`NodeInfo.drain.watch_error`. The agent does not keep taints across a restart: if the first read after a
restart fails, the agent has no taints and admits VMs on a cordoned Node until a read works. Set the
manual flag (`SetDrain`) before a planned drain to close this gap.

- A draining node refuses every Create that would start a new VM with `NODE_DRAINING`
  (`FAILED_PRECONDITION`); create the VM on another node. A repeat Create of a VM that runs here still
  returns it. It also refuses a template build that must boot a template VM (`BuildTemplate` and the
  start-up build) with `NODE_DRAINING`; a template that is already on the node is still returned.
- Running VMs keep running. Automatic evacuation by the api_server is planned (ENG-4580), not built.
  Until then, save the data you need, `Stop` each VM from `List`, and wait for `NodeInfo.drain.state`
  `DRAINED` before you take the node down.
- `NodeInfo.drain`: `state` (`ACTIVE`, `DRAINING` while VMs are starting or running, while the agent
  keeps Firecracker processes in doubt or runs a template build VM, and while no process scan worked;
  `DRAINED` when none of these is left), `manual`, `taints`, `since`, `watch_error`. While draining,
  `NodeInfo` scans the processes again, so a doubt whose process exited clears. Clearing the manual flag does not end a drain that a
  taint causes.

### Managed drive (ENG-4614)

`/workspace/managed` in each VM is a read-only ext4 drive with the managed files (the skills). The agent
changes it in running VMs, with no restart. Firecracker cannot add a drive after boot, so every VM has two
managed slots: A (drive `managed`, `/dev/vdc`, the image's `MANAGED_DEV`) and B (drive `managed_b`,
`/dev/vdf`, `MANAGED_DEV_B`, the last drive). At Create, slot A has the template's empty placeholder and
attach mounts it; slot B is never mounted by attach.

**Images.** `PutManagedImage` streams a zip (first message: SHA256 and size; then data, at most 4 MiB per
message). The image ID is the zip's SHA256. The agent:

1. writes the zip to `<data-dir>/managed/.upload-*` and checks its size and SHA256
   (`MANAGED_BUNDLE_INVALID`);
2. unpacks it into a tmpfs of its own (`--managed-max-mib` plus room for directories), so the files stay
   in memory. Only plain relative paths, regular files and directories are allowed: an absolute or `..`
   path, a symlink, device, FIFO or socket, a duplicate name or a file and directory with one name fails
   the whole bundle. Content is counted as it is read (`--managed-max-mib`, `--managed-max-files`), so a
   zip bomb stops at the limit. Files become root-owned 0644 (0755 with an execute bit), directories
   0755;
3. runs `mkfs.ext4 -d` (4 KiB blocks, no journal, no reserved blocks, root owner, label `managed`) into
   `<data-dir>/managed/<id>.ext4`, with an ext4 UUID derived from the ID. The size is an estimate with
   room; a full file system gets two more tries at twice the size;
4. writes `<id>.json` (ext4 SHA256, size, UUID, file count). A repeat upload of the same zip returns the
   image without reading the data.

At most `--managed-max-builds` (default 1) uploads do steps 1 to 4 at once on a node; the others wait
before they read their data. So the disk and tmpfs use of uploads together stays within one bundle limit
per build.

GC (after each upload and swap) keeps the `--managed-keep` (default 3) newest images, every image that
a VM has behind a slot, and the image of a swap that runs. It does not touch an image while its upload
runs. Each VM chroot has its own reflink copy, so GC never changes a running VM.

**Swap.** `SwapManaged` takes an image ID and the target VMs, each with its attempt, generation and
`sandboxd_key` (the agent does not keep the key, so the caller sends it). It swaps one VM at a time, in
order; one failure does not stop the others. For each VM:

1. Daemon `ManagedStatus` (vsock, with the key): which slot is on `/workspace/managed`, and whether each
   slot device is in use. The guest is the truth, so a swap that an agent restart cut short is seen here.
   If the active slot already has the image's UUID, the call only fixes the journal (`changed` false).
2. The idle slot is the other one. If the guest still uses it (a detached mount from the last swap with
   open files), the VM gets `MANAGED_SLOT_BUSY` and nothing changes. If the busy slot already has the
   image's UUID, a swap stopped after its guest mount: the agent skips step 3, and `MountManaged`
   detaches the old top mount.
3. The journal records the pending swap. The agent puts a reflink copy of the image at
   `/managed.ext4` or `/managed-b.ext4` in the chroot and calls Firecracker `PATCH /drives/<id>`.
4. Daemon `MountManaged(slot, size, uuid)`: wait until the device has the new size (Firecracker sends a
   virtio config change), drop the guest's cached blocks (`BLKFLSBUF`), check the ext4 UUID, mount the
   device `ro,noload,nodev,nosuid,noexec` with private propagation beneath the current mount
   (`fsmount` + `move_mount(MOVE_MOUNT_BENEATH)`, Linux 6.5+), then detach the old top mount
   (`umount2(MNT_DETACH)`). Open files on the old drive keep working until they close.
5. The journal records the new active slot and image.

The result per VM has `active`, `changed`, `ms` and `previous_in_use` (a guest process still has a file
open on the old drive; the next swap of this VM gets `MANAGED_SLOT_BUSY` until it closes). Stop and
Create of a sandbox wait for its swap; other calls (the pass-through) go on during a swap.

Firecracker v1.17 `PATCH /drives` with `path_on_host` works after boot and after a snapshot restore. It
opens the new file with the drive's read-only flag, sets the new capacity and sends a config change
interrupt (`devices/virtio/block/virtio/device.rs`, `update_disk_image`). Its documented contract is that
the guest does not mount or read the device during the change: the idle slot check (an exclusive open of
the device fails with `EBUSY` while any mount holds it) gives that.

Flags: `--managed-keep` (3), `--managed-max-zip-mib` (256), `--managed-max-mib` (512),
`--managed-max-files` (50000), `--managed-max-builds` (1), `--managed-swap-timeout` (30 s per VM).

Errors: `MANAGED_IMAGE_MISSING`, `MANAGED_BUNDLE_INVALID`, `MANAGED_SWAP_UNSUPPORTED` (layout 2 template,
or a daemon without `MountManaged`), `MANAGED_SLOT_BUSY`, `MANAGED_MOUNT_FAILED` (the old drive stays
mounted), `GUEST_KEY_REJECTED` (wrong `sandboxd_key`), `GUEST_UNREACHABLE`.

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
# Rootfs delivery (ENG-4648): the root drive image (deployment/craft-fc/rootfs/Dockerfile.image, from a
# build without --ca) installs into <data-dir>/rootfs, the agent builds a template, and VMs trust only the
# --egress-ca of their agent (a MITM proxy as --egress-proxy). A second CA keeps the same template.
KVM_RD_IMAGE=craft-fc-rootfs:dev KVM_RD_DIR=/opt/rd/work ./hostagent-kvm.test -test.v -test.run TestRootfsDeliveryKVM
# Managed drive swap (ENG-4614): same inputs; KVM_VMS running VMs, a reader in each VM holding files on the
# managed drive, swaps of every VM, guest checks (content, old reader, noexec, no rw remount, no restart).
KVM_TB_ROOTFS=/opt/tb/rootfs-out KVM_TB_CA=/opt/tb/ca/ca.crt ./hostagent-kvm.test -test.v -test.run TestManagedSwapKVM
# Memory, admission and drain (ENG-4569): same inputs, root drive built with
# --daemon-cmd "/craft-fc/bin/guest-daemon --reclaim-idle=1m"; balloon on restores, reclaim on KVM_VMS
# idle VMs, scope limits and a guest memory hog, fill the node to CAPACITY_MEMORY, manual drain.
KVM_TB_ROOTFS=/opt/tb/rootfs-out KVM_TB_CA=/opt/tb/ca/ca.crt ./hostagent-kvm.test -test.v -test.run TestMemAdmissionKVM
# Files and session saves through the agent over mTLS: file calls through the pass-through,
# capture → presigned PUT → restore into a fresh VM, with a test S3 bucket (KVM_S3_BUCKET; AWS
# credentials on the host sign the URLs, the agent never sees them). Results: results/daemon-files.md.
KVM_IMG_DIR=/opt/craft-fc-test/img3 KVM_S3_BUCKET=<bucket> ./hostagent-kvm.test -test.v -test.run TestSavesKVM
```

The KVM tests take the template version from the build (`KVM_TEMPLATE` is no longer used).

To check relay tokens against the proxy verifier on a dev machine:
`RELAY_TOKENS_OUT=/tmp/tokens.json go test -run TestWriteTokensForProxyVerifier ./internal/relay/`, then run
`verify_tokens.py` from the test kit with the backend Python env.
