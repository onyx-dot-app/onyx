# Craft Firecracker VM root drive

This directory converts the Craft sandbox image (`onyxdotapp/sandbox:<version>`)
into the read-only root drive of a Craft Firecracker VM. It also has the guest
init. The pod runtime keeps using the sandbox image as it is: the build does not
change the image or its Dockerfile.

## Files

| File | Installed as | What it does |
|---|---|---|
| `build-rootfs.sh` | – | Builds `rootfs.ext4` and `manifest.json` |
| `craft-init` | `/sbin/craft-init` | PID 1: mounts, attach, starts and restarts the services |
| `attach.sh` | `/craft-fc/lib/attach` | Mounts the scratch drive, the overlays and the managed drive |
| `egress-relay.py` | `/craft-fc/bin/egress-relay` (only with `--python-relay`) | Fallback egress relay. The default is the static Go relay from `microvm/cmd/egress-relay` (`--relay-bin`). |
| `init.conf` | `/craft-fc/etc/init.conf` | Settings: daemon command, drive names, overlay directories |

The build also writes `/craft-fc/etc/guest.env` (the service environment),
installs the daemon as `/craft-fc/bin/guest-daemon` (or the `--daemon-cmd`
program path), and installs a static
busybox (Debian `busybox-static`) as `/craft-fc/bin/busybox`.

### Rule: supervised programs live outside the overlays

Every program that init starts or restarts, and `attach`, is in `/craft-fc`.
`/craft-fc` is a top-level directory on the read-only root drive. It is never
in the overlay list, so root in the guest cannot replace or delete what init
restarts. Do not use `/sbin` or `/usr/...`: the image has a merged `/usr`
(`/sbin` is a link to `usr/sbin`), and `/usr` has a writable overlay.

- `craft-init` starts no service if `/craft-fc` is on a writable mount.
- `attach` stops if `/craft-fc` is on a writable mount, or if `OVERLAY_DIRS`
  has `/`, `/craft-fc` or a directory below it.
- `/sbin/craft-init` stays where it is: it is PID 1 and the kernel starts it
  from the read-only root before any overlay exists.
- The helpers are also protected. After `attach`, init runs only bash builtins
  and `/craft-fc/bin/busybox` by absolute path (its `PATH` is `/craft-fc/bin`).
  `attach` runs in the busybox shell (`#!/craft-fc/bin/busybox sh`), which runs
  its commands itself. A program, a shared library or `/etc/ld.so.preload`
  from the overlays never runs as root on the restart path. A saved scratch
  disk can bring back changes to `/usr` and `/etc` at the next boot, so this
  also applies to a cold boot.
- The build stops if the daemon, the Go egress relay (`--relay-bin`) or busybox
  is not a static x86-64 executable, or if the `--daemon-cmd` program is not
  `/craft-fc/bin/<name>`.
- The build stops if busybox does not have an applet that init or `attach`
  runs (for example `nsenter` and `setpriv`, which drop the relay's privileges).
- The egress relay is a static Go binary (`--relay-bin`), so it needs no
  interpreter. The Python fallback (`--python-relay`) runs with
  `/usr/local/bin/python3`, which is under the `/usr` overlay. The rule does
  not cover that interpreter, so use the fallback only for tests.

## Build

Run on a Linux x86-64 host as root. The host needs Docker, GNU tar,
e2fsprogs, OpenSSL, `file` and Python 3.9 or later (the AL2023 `python3` is
3.9 and works).

Build the two Go programs first (from the repository root):

```bash
cd microvm
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o ../out/guest-daemon ./cmd/guest-daemon
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o ../out/egress-relay ./cmd/egress-relay
cd ..
sudo deployment/craft-fc/rootfs/build-rootfs.sh --image onyxdotapp/sandbox:v5.1.0 \
  --ca egress-ca.crt --daemon-bin out/guest-daemon --relay-bin out/egress-relay --out out/
```

- `--image`: the sandbox image. The build pins it to its digest.
- `--registry`: optional. Pull the image through this prefix, for example the
  ECR pull-through cache `<account>.dkr.ecr.<region>.amazonaws.com/docker-hub`.
  The manifest records the reference that was pulled.
- `--ca`: the public certificate of the egress proxy CA. The build stops if the
  file has a private key, has more than one certificate or is not a CA.
- `--daemon-bin`: the guest daemon (required), installed at the `--daemon-cmd`
  program path.
- `--relay-bin`: the egress relay, installed as `/craft-fc/bin/egress-relay`.
  The build stops if it is not a static x86-64 executable.
- `--python-relay`: install `egress-relay.py` as the relay instead of
  `--relay-bin` (fallback, for tests).
- `--daemon-cmd`: the command line that init supervises. The default is
  `/craft-fc/bin/guest-daemon`. Its program must be `/craft-fc/bin/<name>`, and
  the value must not have quotes, `$`, backticks, backslashes or newlines. The
  manifest records that path and its SHA256.

Each build exports its own image ID (no shared tag), so two builds can run on
one Docker host at the same time.

The build needs the network: it runs `apt-get` for `zstd` and `xvfb`. The image
has no apt package lists, so an offline install is not possible. The VM never
needs the network at boot.

### What the conversion changes

- Removes `iptables` and `gosu` (apt purge with their unused dependencies),
  `/workspace/firewall-init.sh` and `/workspace/sidecar-entrypoint.sh`. The VM
  has no network card, so the iptables lockdown has no use.
- Adds `zstd` (session capture) and `xvfb` (headful Chromium). Copies the
  static busybox to `/craft-fc/bin/busybox` and removes the `busybox-static`
  package again.
- Checks that `libreoffice-writer` is installed (it is, from v5.1).
- Adds the egress CA:
  - `/usr/local/share/ca-certificates/craft-egress-ca.crt`, then `update-ca-certificates`;
  - `/etc/ssl/sandbox/ca-bundle.crt`, a link to the system bundle (the same
    path as the pod runtime);
  - the sandbox user's Chromium NSS database (`/home/sandbox/.pki/nssdb`).
- Writes the proxy settings:
  - `/craft-fc/etc/guest.env`: the image's `ENV` (Docker export drops it), plus
    `HTTP(S)_PROXY`, `NO_PROXY=localhost,127.0.0.1,::1`, `NODE_USE_ENV_PROXY=1`,
    and `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `PIP_CERT`,
    `NODE_EXTRA_CA_CERTS`, `GIT_SSL_CAINFO` (all set to the bundle);
  - `/etc/profile.d/craft-guest-env.sh` for login shells;
  - `/etc/apt/apt.conf.d/80craft-egress-proxy`.
- Makes `/workspace/managed` an empty, root-owned mount point, and adds
  `/mnt/scratch`.
- Writes `/etc/hosts`, `/etc/hostname` and an empty `/etc/resolv.conf`. There is
  no DNS in the VM.
- Makes an ext4 file system with no journal (the drive is always read-only).

The build stops if it finds a private key in `/etc`, `/root`, `/home`,
`/workspace` or the Craft files. There are no secrets in the root drive. The
egress CA certificate is public. The daemon gets per-VM values from the host
in its `Init` call.

The egress CA is a build input, so each CA needs its own root drive. Aiohttp
clients still need `trust_env=True` in code. An environment variable cannot set
it.

### Output

- `rootfs.ext4`: sparse ext4 image, label `craft-root`.
- `manifest.json`, for the per-node template build:

| Field | Content |
|---|---|
| `source_image` | `ref`, `pulled_from`, `pinned` (`repo@sha256:…`), `digest`, `platform` |
| `build_inputs` | onyx commit, SHA256 of each file in this directory, the CA fingerprint, subject and expiry, packages added, removed and changed, files removed |
| `guest` | init path, `boot_args`, `template_boot_args_extra`, `supervised_dir` (`/craft-fc`), attach (path, SHA256), busybox (path, SHA256), daemon (command, path, SHA256, vsock port 52), egress relay (kind `go` or `python`, path, SHA256, uid, PID file), config paths, egress (guest proxy, host vsock port 3128, CA bundle), drive order, overlay directories, scratch layout version |
| `output` | file name, SHA256, size, file system UUID and label |

The output is not reproducible byte for byte: file times and the file system
UUID change with each build. Use the manifest SHA256 to identify a build.

## Drives

Attach the drives in this order. The guest finds them by order:

| `drive_id` | Guest device | `is_read_only` | Content | Mounted on |
|---|---|---|---|---|
| `rootfs` | `/dev/vda` | `true` (root device) | `rootfs.ext4` | `/` |
| `scratch` | `/dev/vdb` | `false` | Per-VM ext4, made by the host (empty or a saved disk) | `/mnt/scratch` |
| `managed` | `/dev/vdc` | `true` | Managed slot A: per-VM ext4 with the managed files (skills) | `/workspace/managed` |
| `upload_a`, `upload_b` | `/dev/vdd`, `/dev/vde` | `true` | Upload slots of the template layout | not by `attach` |
| `managed_b` | `/dev/vdf` | `true` | Managed slot B: the spare for a skills update. Always the last drive, so the other device names do not move. Optional: older templates do not have it | not by `attach` |

`init.conf` sets the managed slot devices: `MANAGED_DEV` (slot A, default
`/dev/vdc`) and `MANAGED_DEV_B` (slot B, default `/dev/vdf`). The manifest
lists them in `guest.managed_slots`.

Kernel boot arguments: `console=ttyS0 reboot=k panic=1 pci=off init=/sbin/craft-init`.
Add `craft.scratch=defer` for a template boot.

The managed drive is read-only in the device. Root in the guest cannot write it,
also not with `mount -o remount,rw` or `blockdev --setrw`. `attach` stops (and
init starts no service) if the guest sees the managed drive as writable. With
no managed drive, `attach` mounts an empty read-only tmpfs on
`/workspace/managed`, so the path is never writable.

`attach` mounts slot A with `ro,noload,nodev,nosuid,noexec` and private mount
propagation. It never mounts slot B. If slot B is there, `attach` only checks
that the guest sees it as read-only.

### Skills update without a new VM

The guest daemon and the node agent do the update (ENG-4614), not `attach`:

1. The host points the idle slot at the new managed image (Firecracker
   `PATCH /drives`).
2. The daemon mounts that slot with the same options on a staging directory
   under `/run/craft-fc`, and moves a clone of it beneath the current mount
   (`open_tree` with `OPEN_TREE_CLONE`, then `move_mount` with
   `MOVE_MOUNT_BENEATH`, Linux 6.5 or later).
3. The daemon unmounts the top (old) mount of `/workspace/managed` with
   `MNT_DETACH`, then the staging mount. New opens see the new files at once.
   Open files of the old mount keep working until they close.
   A plain stacked mount does not work here: after the new mount goes on top,
   no path reaches the old mount, so it cannot be unmounted.
4. The old slot is now idle. The next update uses it (step 1).

The daemon makes the new mount private too. Private mounts keep these mount
and unmount events local. A container check (kernel 7.0) passed this order.

Root in the guest can unmount `/workspace/managed` and then write to the
directory below it. Those files go to the user's own scratch disk; the
managed drive does not change. Nothing on the host reads `/workspace/managed`
from the guest.

## Init

`craft-init` is a bash script of about 150 lines of code. A shell script is easy to
audit and needs no build toolchain. All its steps are mount and process
commands. Each service has its own supervisor (a subshell of PID 1, no new
program) that waits for that one PID, so no exit is missed, also not one
during a backoff. PID 1 reaps orphan processes that the kernel moves to it.

At boot, init:

1. Mounts `/proc`, `/sys`, `/dev`, `/dev/pts`, `/dev/shm`, cgroup2 on
   `/sys/fs/cgroup` (all controllers on in `cgroup.subtree_control`), and
   tmpfs on `/run` and `/tmp`.
2. Sets the host name to `sandbox` and starts the loopback interface.
3. Stops here, without services, if `/craft-fc` is on a writable mount. Only
   then does it read `init.conf`.
4. Runs `attach`, unless the kernel command line has `craft.scratch=defer`.
   If `attach` fails, init starts no service (the host sees no daemon and
   fails the VM).
5. Starts two services with only the `guest.env` environment:
   - the guest daemon (`DAEMON_CMD`, default `/craft-fc/bin/guest-daemon`,
     vsock port 52), as root;
   - the egress relay, as uid 65534 with no extra groups, no capabilities and
     `no_new_privs` (`busybox nsenter -F -G -S`, then `busybox setpriv --nnp`).
     Busybox `setpriv` cannot clear the capability bounding set. With a
     non-root uid and `no_new_privs`, no exec can get a capability, so the
     bounding set has no effect.
6. Restarts a service when it stops: at once after a run of 10 s or more,
   otherwise after 1, 2, 4, then 5 s. If guest root kills a supervisor, PID 1
   stops that orphan service and starts a new supervisor within 5 s.

Init never exits, because the kernel panics when PID 1 exits. It ignores
signals. `kill -9 1` in the guest has no effect.

Logs:
- `/run/craft-fc/init.log` and `/dev/kmsg` (init);
- `/run/craft-fc/log/<service>.log`. Every 5 s, init copies a log over 4 MiB to
  `<log>.1` and empties it. The services append to the file, so they keep
  writing. This also applies to `init.log` and `attach.log`;
- `/run/craft-fc/log/attach.log`.

PID files: `/run/craft-fc/guest-daemon.pid` and `/run/craft-fc/egress-relay.pid`.

## Attach and overlays

`attach` does these steps:

1. Flushes the scratch device buffers (`blockdev --flushbufs`).
2. Mounts the scratch drive on `/mnt/scratch`.
3. Mounts an overlay on each of `/etc /home /root /opt /srv /usr /var /workspace`.
   The read-only root is the lower layer. The upper layer is
   `/mnt/scratch/overlay/<name>/upper` (for example `overlay/usr/upper`).
4. Mounts managed slot A read-only and `noexec`, with private propagation, on
   `/workspace/managed`, or an empty read-only tmpfs if there is no managed
   drive. Slot B stays unmounted.

There is no overlay over the whole root. A saved scratch disk holds only the
changes under these directories, so it can go on top of a shared template. `/usr`
has an overlay (not only `/usr/local`), because `apt-get install` writes to
`/usr/bin` and `/usr/lib`. `/var` has an overlay because apt also writes
`/var/cache` and `/var/log`. `/tmp` is tmpfs and is not saved.

`/mnt/scratch/.craft-layout` has the layout version (now `1`). `attach` stops if
a saved disk has a different version. A second run does nothing.

## Template and restore order

The template build (ENG-4566) must not snapshot a guest with the scratch drive
mounted. A scratch disk that changes under a mounted file system corrupts it.
Use this order:

1. Template boot with `craft.scratch=defer`. Attach every drive of the
   template layout. The scratch and managed files can be empty placeholders. Init starts the daemon and the
   relay. It does not mount the scratch or managed drive.
2. Wait for the daemon health check. Pause the VM and create the snapshot.
3. For each VM: put the VM's own `scratch.ext4` and `managed.ext4` at the drive
   paths of the template, then load the snapshot.
4. The node agent closes its relay connections for the VM (`CloseConnections`).
5. The daemon `Init` sets the clock, runs `/craft-fc/lib/attach` and sends
   `SIGHUP` to the PID in `/run/craft-fc/egress-relay.pid` (init writes that
   file each time it starts the relay). On `SIGHUP` the relay resets every live
   connection (TCP RST). Pooled clients and open streams then fail at once
   instead of hanging, and connect again.

A cold boot without `craft.scratch=defer` runs `attach` at boot. Use it for
tests and for a VM without a template. When the daemon `Init` then runs
`attach` again, it does nothing.

## Change the daemon

The daemon from ENG-4571 is `/craft-fc/bin/guest-daemon` on vsock port 52. To
use another program, set `--daemon-cmd`, or edit `DAEMON_CMD` in `init.conf`.
If the daemon serves the egress proxy itself, set `EGRESS_RELAY_CMD=` (empty). Keep any new command in `/craft-fc` (see the rule above).

## Test

The build has no CI boot test, because CI runners have no `/dev/kvm`. Before
you change `craft-init`, `attach.sh` or the drive layout, boot the result on a
KVM host (see `../README.md`, "Boot test") and check:

- `/proc/mounts` has the overlays and the read-only managed drive;
- `apt-get install`, `pip install` and `npm install -g` work as root;
- writes to `/workspace/managed` fail, also after `mount -o remount,rw`, and
  a program on it does not run (`noexec`);
- with slot B attached: it is not mounted, and a stacked mount of slot B plus
  a lazy unmount of slot A leaves slot B on `/workspace/managed`;
- after `kill -9` of the daemon, init starts it again and the guest keeps running;
- a service that stops during the other service's backoff starts again;
- a failed `attach` (for example no scratch drive) starts no service;
- the relay runs as uid 65534 with `NoNewPrivs: 1` and no capabilities;
- `curl https://…` works through `127.0.0.1:3128`.
