# Guest daemon and egress relay

Two static binaries run inside each Craft micro-VM: the guest daemon (`cmd/guest-daemon`) and the egress
relay (`cmd/egress-relay`). The VM init (`deployment/craft-fc/rootfs/craft-init`, ENG-4574) starts and
restarts both, as separate processes. Both live on the read-only root, outside every writable overlay, so
root in the guest cannot replace them.

## Guest daemon

The guest daemon (ENG-4571) serves the `Sandboxd` gRPC API
(`proto/sandboxd/v1/sandboxd.proto`) on vsock. The api_server reaches it through the node agent: the
agent forwards daemon calls to the VM by sandbox ID (design: `plans/craft-fc-track-daemon.md`).

Code: `cmd/guest-daemon/` (main), `internal/guestd/` (API, Init, auth), `internal/guestd/execs/`
(commands), `internal/guestd/sysops/` (clock, entropy, attach, file system grow, cgroup mount),
`internal/guestd/vsock/` (guest vsock listener and dialer).

### Contract with the VM image (ENG-4574)

| Item | Value |
|---|---|
| Binary | `/craft-fc/bin/guest-daemon` (static, `CGO_ENABLED=0`, read-only root) |
| vsock port | **52** (the node agent's default `--daemon-port` for the gRPC pass-through; `Dial` always refuses it) |
| User and env | root (decision P2), with the env `craft-init` passes from `/craft-fc/etc/guest.env`. Commands get that env, then the Init env, then their own. |
| Supervisor | `craft-init` (PID 1) starts the daemon and restarts it when it exits. The daemon is not PID 1. |
| cgroup v2 | Mounted at `/sys/fs/cgroup` by init. The daemon mounts it if it is missing, and makes `/sys/fs/cgroup/guestd/`. |
| Drives | Init runs `/craft-fc/lib/attach` (scratch on `/mnt/scratch`, overlays, read-only managed drive). It does nothing if init already attached them. |
| Egress relay | Init sends SIGHUP to the PID in `/run/craft-fc/egress-relay.pid`. |
| Scratch disk | ext4 on `/mnt/scratch`. Init grows it to the device size, and fails if the device is still smaller than `scratch_bytes` after about 1 s. |
| Init state | `/run/craft-fc/guest-daemon-init.json` (mode 0600, tmpfs). A restarted daemon keeps its key, env and session list. |
| Logs | stderr, text. |

Flags (defaults in brackets): `--port` (52), `--attach-cmd` (`/craft-fc/lib/attach`; empty to skip),
`--relay-pidfile` (`/run/craft-fc/egress-relay.pid`; empty to skip), `--cgroup-root`
(`/sys/fs/cgroup/guestd`), `--state-file`, `--grow-fs` (`/mnt/scratch`), `--default-deadline` (30m),
`--max-deadline` (24h), `--output-bytes` (4 MiB per stream), `--output-budget` (256 MiB for all
executions), `--max-running` (64), `--listen`
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
| `SetKey` | Node agent only (the pass-through refuses it). Installs the per-VM key once. Before it, every call but `Health` fails with `KEY_NOT_SET`. |
| `Init` | Needs the key. Sets `CLOCK_REALTIME`, adds the entropy with `RNDADDENTROPY` (credited) and `RNDRESEEDCRNG`, runs attach, grows `--grow-fs` mounts (`EXT4_IOC_RESIZE_FS`) after a device size check, resets the egress relay, stores env and sessions. Other calls fail with `NOT_INITIALIZED` until it succeeds. |
| `Run` | Starts a command and streams `started`, output chunks (with byte offsets) and the result. |
| `Start` | Starts a command and returns its execution ID at once. |
| `Stream` | Output of an execution from given offsets, then the result. Works after a dropped client. |
| `Interact` | Writes to (or closes) the stdin of a command started with `stdin: true`. |
| `Cancel` | Kills the command's cgroup and returns the result (`CANCELED`, or `EXITED` if the command exited first). Not an error. |
| `Inspect`, `List` | Execution records (state, PID, times, byte counts, result), `List` filtered by labels. |
| Files, `CaptureSession`, `RestoreSession` | Reserved for ENG-4572. `UNIMPLEMENTED`. |
| `BrowserStart`, `BrowserStop` | Reserved for ENG-4573. `UNIMPLEMENTED`. |

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

Errors are gRPC statuses with one `google.rpc.ErrorInfo`: domain `sandboxd.craft.onyx.app`, reason an
`ErrorReason` name (`KEY_NOT_SET`, `NOT_INITIALIZED`, `UNAUTHENTICATED`, `EXECUTION_NOT_FOUND`, ...).

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
- KVM: build tag `kvm`. They boot Firecracker directly (no node agent) with the ENG-4574 root drive
  (`build-rootfs.sh --daemon-bin`), and call the daemon over `v.sock` (`CONNECT 52`). The egress relay
  subtest copies the relay into the VM with `Interact` and serves a host echo on `v.sock_3128`. Host
  setup: `plans/craft-sandbox-bench/work-guest-daemon/`.

```bash
GOOS=linux GOARCH=amd64 go test -c -tags kvm -o guestd-kvm.test ./internal/guestd/kvmtest
# As root. KVM_FC_BIN, KVM_IMG_DIR (vmlinux, rootfs.ext4, scratch-empty.ext4, managed-empty.ext4),
# KVM_WORK_DIR, KVM_VMS=20, KVM_BOOT_ARGS, KVM_TEMPLATE_ARGS (craft.scratch=defer), KVM_RELAY_BIN.
./guestd-kvm.test -test.v -test.run 'TestDaemonKVM|TestRestoreKVM'
```
