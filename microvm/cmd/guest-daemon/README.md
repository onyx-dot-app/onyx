# Guest daemon and egress relay

Two static binaries run inside each Craft micro-VM: the guest daemon (`cmd/guest-daemon`) and the egress
relay (`cmd/egress-relay`). The VM init (`deployment/craft-fc/rootfs/craft-init`) starts and
restarts both, as separate processes. Both live on the read-only root, outside every writable overlay, so
root in the guest cannot replace them.

## Guest daemon

The guest daemon serves the `Sandboxd` gRPC API
(`proto/sandboxd/v1/sandboxd.proto`) on vsock. The api_server reaches it through the node agent: the
agent forwards daemon calls to the VM by sandbox ID (design: `plans/craft-fc-track-daemon.md`).

Code: `cmd/guest-daemon/` (main), `internal/guestd/` (API, Init, auth), `internal/guestd/execs/`
(commands), `internal/guestd/sysops/` (clock, entropy, attach, file system grow, cgroup mount),
`internal/guestd/vsock/` (guest vsock listener and dialer).

### Contract with the VM image

| Item | Value |
|---|---|
| Binary | `/craft-fc/bin/guest-daemon` (static, `CGO_ENABLED=0`, read-only root) |
| vsock port | **52** (the node agent's default `--daemon-port` for the gRPC pass-through; `Dial` always refuses it) |
| User and env | root (decision P2), with the env `craft-init` passes from `/craft-fc/etc/guest.env`. Commands get that env, then the Init env, then their own. |
| Supervisor | `craft-init` (PID 1) starts the daemon and restarts it when it exits. The daemon is not PID 1. |
| cgroup v2 | Mounted at `/sys/fs/cgroup` by init. The daemon mounts it if it is missing, and makes `/sys/fs/cgroup/guestd/`. |
| Drives | Init runs `/craft-fc/lib/attach` (scratch on `/mnt/scratch`, overlays, read-only managed drive). It does nothing if init already attached them. |
| Managed slots | Slot A `/dev/vdc` (`MANAGED_DEV`, mounted by attach) and slot B `/dev/vdf` (`MANAGED_DEV_B`, never mounted by attach) on `/workspace/managed`. `MountManaged` changes the drive there. Needs a guest kernel with `MOVE_MOUNT_BENEATH` (6.5+). |
| Egress relay | Init sends SIGHUP to the PID in `/run/craft-fc/egress-relay.pid`. |
| Scratch disk | ext4 on `/mnt/scratch`. Init grows it to the device size, and fails if the device is still smaller than `scratch_bytes` after about 1 s. |
| Init state | `/run/craft-fc/guest-daemon-init.json` (mode 0600, tmpfs). A restarted daemon keeps its key, egress CA, env and session list. |
| Egress CA | `SetKey` can carry the deployment egress CA (`egress_ca_pem`). `Init` installs it after attach: `--ca-anchor`, `--ca-bundle` (old egress CA removed, new one added) and `--ca-nssdb` (`certutil` as the database owner, never root; a failure is only logged). |
| Logs | stderr, text. |

Flags (defaults in brackets): `--port` (52), `--attach-cmd` (`/craft-fc/lib/attach`; empty to skip),
`--relay-pidfile` (`/run/craft-fc/egress-relay.pid`; empty to skip), `--cgroup-root`
(`/sys/fs/cgroup/guestd`), `--state-file`, `--grow-fs` (`/mnt/scratch`), `--default-deadline` (30m),
`--max-deadline` (24h), `--output-bytes` (4 MiB per stream), `--output-budget` (256 MiB for all
executions), `--max-running` (64), `--managed-mount` (`/workspace/managed`; empty turns the managed calls
off), `--managed-dev-a` (`/dev/vdc`), `--managed-dev-b` (`/dev/vdf`), `--ca-anchor`
(`/usr/local/share/ca-certificates/craft-egress-ca.crt`), `--ca-bundle` (`/etc/ssl/certs/ca-certificates.crt`;
empty turns the CA install off), `--ca-nssdb` (`/home/sandbox/.pki/nssdb`; empty to skip), `--certutil`
(`/usr/bin/certutil`), the file flags (`--sessions-root`,
`--read-link-roots`, `--max-file-bytes`, `--max-zip-bytes`, `--capture-dirs`, `--capture-exclude`,
`--capture-max-stored-bytes`, `--capture-max-expanded-bytes`, `--capture-max-entries`,
`--capture-zstd-level`; see Files), `--listen`
(`unix:<path>` instead of vsock, for tests; mode 0600), `--log-level`. The daemon has no TCP listener:
the API is plaintext with a bearer key, so it is served only on vsock, through the node agent. The
container fallback (TCP with mTLS) is not in v1.

The daemon builds its gRPC server itself (`guestd.Server.NewGRPCServer`), with the key check on every
call except `Health` and `SetKey`. Limits are checked at start: a negative limit, or a default deadline above `--max-deadline`, is an
error.

Build:

```bash
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=<v>" -o guest-daemon ./cmd/guest-daemon
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=<v>" -o egress-relay ./cmd/egress-relay
```

### Bring-up sequence (api_server)

1. Node agent `Create` with a new per-VM key in `sandboxd_key` (restore from the template, booted with
   `craft.scratch=defer`). Before Create returns, the agent installs the key with the daemon's `SetKey`
   over vsock. So no other caller can set a key first.
2. Node agent `CloseConnections(sandbox_id, attempt, generation)`. **Do this before Init.** A restore
   keeps the guest's pooled egress connections, which then hang (T5 in `results/prebuild.md`). After a
   cold boot there is nothing to close; the call is harmless.
3. Daemon `Init`, with the key: host time (add half the measured round trip), 32+ bytes of host entropy
   (`os.urandom`), env, session IDs, generation, sandbox ID and `scratch_bytes`. In the guest, Init sets
   the clock, adds the entropy and reseeds the CRNG, runs attach, grows the scratch file system and sends
   SIGHUP to the egress relay (the guest side of the reset in step 2).
4. Every call except `Health` sends the key in the `x-sandboxd-key` metadata.

The template must not call `SetKey` or Init: it would bake a key into the snapshot. The first key stays:
`SetKey` with the same key succeeds again (a Create retry), with another key it fails with
`KEY_ALREADY_SET`. The node agent pass-through refuses `SetKey`. The key must be printable ASCII with no
spaces (for example the hex of 32 random bytes), because calls send it as metadata. Through the node
agent, every call also carries `x-sandbox-id`.

### API

| Call | What it does |
|---|---|
| `Health` | Answers before Init, with no key. Initialized and key-set flags, version, guest time, generation, running count. |
| `SetKey` | Node agent only (the pass-through refuses it). Installs the per-VM key once, and keeps the egress CA (`egress_ca_pem`) for `Init`; a repeat call with the same key can replace the CA. Before it, every call but `Health` fails with `KEY_NOT_SET`. |
| `Init` | Needs the key. Sets `CLOCK_REALTIME`, adds the entropy with `RNDADDENTROPY` (credited) and `RNDRESEEDCRNG`, runs attach, grows `--grow-fs` mounts (`EXT4_IOC_RESIZE_FS`) after a device size check, installs the `SetKey` egress CA, resets the egress relay, stores env and sessions. Other calls fail with `NOT_INITIALIZED` until it succeeds. |
| `Run` | Starts a command and streams `started`, output chunks (with byte offsets) and the result. |
| `Start` | Starts a command and returns its execution ID at once. |
| `Stream` | Output of an execution from given offsets, then the result. Works after a dropped client. |
| `Interact` | Writes to (or closes) the stdin of a command started with `stdin: true`. |
| `Cancel` | Kills the command's cgroup and returns the result (`CANCELED`, or `EXITED` if the command exited first). Not an error. |
| `Inspect`, `List` | Execution records (state, PID, times, byte counts, result), `List` filtered by labels. |
| `ReadFile`, `WriteFile`, `UploadFile`, `ListFiles`, `DeleteFile`, `ZipFiles` | Session files (see Files). |
| `CaptureSession`, `RestoreSession` | Session saves as tar + zstd (see Session saves). |
| `BrowserStart`, `BrowserStop` | Reserved for the browser. `UNIMPLEMENTED`. |
| `ManagedStatus` | The slot on `/workspace/managed` (by the mount's device number) and, per slot, the device, size, ext4 UUID (read with `O_DIRECT`) and whether it is in use (an exclusive open fails with `EBUSY` while a mount holds it, also a detached one with open files). The node agent calls it. |
| `MountManaged(slot, size_bytes, fs_uuid)` | Makes the slot the drive on `/workspace/managed`, in this order: refuse a slot in use (`MANAGED_SLOT_BUSY`); wait up to 5 s for the device size (Firecracker's config change after `PATCH /drives`); `BLKFLSBUF`; check the ext4 UUID (`MANAGED_DEVICE_MISMATCH`); `fsopen`/`fsmount` (`ro`, `noload`; `nodev`, `nosuid`, `noexec`, private) and `move_mount(MOVE_MOUNT_BENEATH)` beneath the current mount; `umount2(MNT_DETACH)` of the old top mount. Open files on the old drive keep working. The same slot with the same UUID is a no-op (`changed` false). A slot in use that is mounted beneath the top mount with the requested UUID is a swap that stopped before its detach: the call detaches the old top mount and finishes it. The node agent calls it during `SwapManaged`. |

Why the mount goes beneath: a mount covered by another mount cannot be reached by path, and a lazy
unmount of it (also through `/proc/self/fd/<n>`) removes the top mount instead (tested on #17241).
`MOVE_MOUNT_BENEATH` puts the new drive under the old one; the old top mount then detaches by path, and
the new drive shows at once.

Commands:

- Each command runs as root in its own cgroup `/sys/fs/cgroup/guestd/<execution_id>` (started there with
  `clone3(CLONE_INTO_CGROUP)`), in a new session.
- The deadline is 30 min unless the call sets one (at most `--max-deadline`). At the deadline, or on
  Cancel, the daemon writes `cgroup.kill`: every process dies, also ones that called `setsid`.
- When the main process exits, the daemon kills what is left in its cgroup. A background server must run
  as its own execution, with a long deadline.
- Every execution ends with one `ExecResult`: the completion marker. `completion` is `EXITED` (with
  `exit_code`), `SIGNALED`, `CANCELED` or `DEADLINE_EXCEEDED`.
- Records and the last `--output-bytes` of each stream stay in memory after the client goes away: ended
  records for 1 h (at most 256). A timer removes expired records, also when no new command starts.
- All kept output is capped by `--output-budget`. Over it, the daemon drops the output of ended records
  (oldest first) down to 3/4 of the budget, then keeps only the latest bytes of running ones. The
  records and results stay; a `Stream` gets an `OutputGap`.
- A relative `PATH` entry (for example `node_modules/.bin`) is relative to the command's working
  directory.
- A command can make child cgroups in its cgroup. The daemon removes them, deepest first, when the
  command ends. A `Stream` from an offset that is gone gets an `OutputGap` first.
- A daemon restart loses the records. At start-up the daemon kills every command left in its cgroups
  and removes the cgroups. If that fails, the daemon does not start (init starts it again).
- Execution IDs come from `crypto/rand`: userspace PRNG state is the same in every clone of a snapshot.

Files (`internal/guestd/files`):

- Every path is relative to `/workspace/sessions/<session_id>/` (`--sessions-root`). Leading `/` are
  dropped, so `/attachments/a.pdf` is `attachments/a.pdf`. The daemon opens that directory as an `os.Root`. A
  path with a `..` part, a NUL byte or bad UTF-8, a path over 4096 bytes, a name over 255 bytes, or a
  symlink that leaves the directory fails with `INVALID_ARGUMENT`. Only `ReadFile`, `ListFiles` and
  `ZipFiles` follow a top-level session link into `--read-link-roots` (default `/workspace/managed`,
  for `user_library`).
- `ReadFile` streams the file info, then 64 KiB chunks. `offset`/`length` read a range. More than
  `--max-file-bytes` (1 GiB) in one call fails with `LIMIT_EXCEEDED`.
- `WriteFile` and `UploadFile`: a header with the exact size (at most `--max-file-bytes`) and an optional
  SHA-256, then data messages (at most 1 MiB each). The daemon writes a temp file in the target
  directory and renames it only when all bytes arrived and match. `WriteFile` without `overwrite` fails
  with `FILE_EXISTS`. `UploadFile` is the direct upload call: it stores the file in `attachments/` (or
  `directory`) under a free name (`a.pdf`, `a_1.pdf`, ...), the same rule as the pod runtime.
- `ListFiles`: directories first, then by name. `recursive` with `max_depth` (64), `exclude_names`,
  `skip_hidden`, `max_entries` (10,000, at most 100,000); `truncated` when cut, also when the
  response would pass 12 MiB. Links are listed, not followed. Names that are not valid UTF-8
  are left out.
- `DeleteFile` removes a file or a link (never its target); a directory needs `recursive`.
- `ZipFiles` streams a deflate zip of the regular files under a directory. It checks
  `--max-zip-bytes` (1 GiB) and 100,000 files before it sends the first byte.

Session saves:

- `CaptureSession` archives the capture roots `--capture-dirs` (default `attachments`) of the
  session as PAX tar + zstd (`--capture-zstd-level`, default `fastest`: in a 2 vCPU VM it encodes at
  ~2 GB/s against ~220 MB/s for `default`, and the T2 archive was not larger), and leaves out `--capture-exclude` names at any depth
  (`node_modules`, `.venv`, `venv`, `__pycache__`, `.next`, caches, ...) and every directory with
  `pyvenv.cfg`. Symlinks, special files and names that are not UTF-8 are skipped. The request can set its own roots and exclude
  list. The last message is the summary with the stream's SHA-256. Limits (A6): 1 GiB stored, 4 GiB of
  files, 500,000 entries (`--capture-max-*`); a request can only lower them.
- `RestoreSession` takes a header (exact size, SHA-256, roots, limits), then the archive. It extracts
  into `.craft-restore-<random>` in the session directory, then checks size and SHA-256 of the whole
  stream, then swaps each root that the archive has into place. It refuses (`ARCHIVE_INVALID`) absolute
  names, `..`, unclean names, names outside the roots, links, devices, FIFOs, sparse members and
  duplicate files, and stops at the limits (`LIMIT_EXCEEDED`), at a zstd window over 64 MiB and at a
  decoded stream larger than the files plus 16 KiB per member and 64 KiB after the tar end. Modes are
  `& 0777`; the owner is root. An error before the swap does not change the session. If one root
  fails to swap, the daemon tries to move the roots already swapped back. If a rollback rename fails,
  or the daemon stops during the swap, old and new roots can be mixed. The old roots then stay in a
  `.craft-old-*` trash directory, and the next restore or capture puts back each old root that has no
  replacement. The daemon deletes a trash directory only after it recovers all of its roots. A
  capture fails if it cannot put back an old root, so an archive never misses those files.
- File calls and saves open files with `O_NONBLOCK` and directories with `O_DIRECTORY|O_NONBLOCK`,
  and use only regular files, so a FIFO cannot block them. A directory listing reads at most 100,000
  entries of one directory; past that it returns the entries it read and sets `truncated`. Capture
  and zip fail with `LIMIT_EXCEEDED` on a directory over their entry limit.
- A capture and a restore of one session run one at a time.

Errors are gRPC statuses with one `google.rpc.ErrorInfo`: domain `sandboxd.craft.onyx.app`, reason an
`ErrorReason` name (`KEY_NOT_SET`, `NOT_INITIALIZED`, `UNAUTHENTICATED`, `EXECUTION_NOT_FOUND`, ...).

### Memory

The VM has the Firecracker balloon with free page reporting (template layout 4, module README).

- `--page-reporting-order` (default 0): the daemon writes it to
  `/sys/module/page_reporting/parameters/page_reporting_order` at start. A boot parameter has no effect:
  the kernel sets the order when the balloon driver registers. Order 0 reports every free page. `-1`
  leaves the kernel default (9). Without the balloon or the kernel knob, the daemon logs a warning.
- `--reclaim-idle` (default 5m, 0 = off, else at least 1m): after this long with no daemon call open or
  ended (Health does not count; refused calls do not count), the daemon writes 3 to
  `/proc/sys/vm/drop_caches` and 1 to `/proc/sys/vm/compact_memory`, once per idle period. Free page
  reporting then gives the pages to the node. Programs that run with no daemon call (a dev server) do not
  count as activity; a reclaim costs them only page cache misses.

## Egress relay

`/craft-fc/bin/egress-relay`, run by `craft-init` as uid 65534 (code: `cmd/egress-relay`,
`internal/egressrelay`). It replaces `egress-relay.py`, whose interpreter is under the writable `/usr`
overlay.

- Listens on `127.0.0.1:3128` (`HTTP(S)_PROXY` in `guest.env`). Each client gets its own vsock
  connection to the host (CID 2, port 3128), where the node agent relays it to the egress proxy.
- Splices both ways without buffering. When either side ends, it closes both: Firecracker vsock has no
  half-close.
- SIGHUP resets every live connection (RST to the client) and keeps listening. It also resets a client
  whose vsock connection is still opening; that connection is closed when it opens.
- `--max-conns` (256, at least 1): above the cap, a new client is reset at once.
- `--idle-timeout` (0 = none; if set, at least 180 s).
- Keeps accepting after transient `Accept` errors (for example `EMFILE`). It raises its open-file limit to
  the hard limit at start.
- Other flags: `--listen`, `--vsock-cid`, `--vsock-port`, `--upstream unix:<path>` (tests; any other
  value is an error).

## Generated code

Same generators as the host agent (module README). From `microvm/`:

```bash
protoc -I proto -I "$PROTOC_INCLUDE" \
  --go_out=paths=source_relative:proto --go-grpc_out=paths=source_relative:proto \
  proto/sandboxd/v1/sandboxd.proto
```

Python stubs (track D) come from the same file, for example
`python -m grpc_tools.protoc -I microvm/proto -I "$PROTOC_INCLUDE" --python_out=<out> --grpc_python_out=<out> --pyi_out=<out> microvm/proto/sandboxd/v1/sandboxd.proto`.

## Tests

- Unit: `go test -race ./internal/guestd/... ./internal/egressrelay/...` (process groups on any Unix;
  a Unix socket stands in for vsock). The cgroup tests in `internal/guestd/execs` run only as root on
  Linux with cgroup v2.
- KVM: build tag `kvm`. They boot Firecracker directly (no node agent) with the Craft root drive
  (`build-rootfs.sh --daemon-bin`), and call the daemon over `v.sock` (`CONNECT 52`). The egress relay
  subtest copies the relay into the VM with `Interact` and serves a host echo on `v.sock_3128`. Host
  setup: `plans/craft-sandbox-bench/work-guest-daemon/`.

```bash
GOOS=linux GOARCH=amd64 go test -c -tags kvm -o guestd-kvm.test ./internal/guestd/kvmtest
# As root. KVM_FC_BIN, KVM_IMG_DIR (vmlinux, rootfs.ext4, scratch-empty.ext4, managed-empty.ext4),
# KVM_WORK_DIR, KVM_VMS=20, KVM_BOOT_ARGS, KVM_TEMPLATE_ARGS (craft.scratch=defer), KVM_RELAY_BIN.
./guestd-kvm.test -test.v -test.run 'TestDaemonKVM|TestRestoreKVM'
```
