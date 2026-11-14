# Craft Firecracker node preparation

`craft-fc-node-prep.sh` checks a Kubernetes node for Craft Firecracker sandboxes and sets what it can.
Customer guide: https://docs.onyx.app/deployment/kubernetes/craft-firecracker-bare-metal

| Command | Where | What it does |
|---|---|---|
| `check [--data-dir DIR]` | On the node | Checks `/dev/kvm`, Intel CPU with `vmx`, cgroup v2, systemd, host kernel, `vm.max_map_count`, the data dir file system and free disk. Exit 1 on a failed check. |
| `apply [--data-dir DIR] [--xfs-device DEV] [--dry-run]` | On the node, as root | Loads `kvm_intel` and `loop` (kept in `/etc/modules-load.d/onyx-craft-fc.conf`), sets `vm.max_map_count=1048576` (kept in `/etc/sysctl.d/99-zz-onyx-firecracker.conf`), makes the data dir, then runs `check`. With `--xfs-device`, it formats an empty device with `mkfs.xfs -m reflink=1`, adds it to `/etc/fstab` by UUID and mounts it at the data dir. |
| `label --context CTX [--pod-sandbox] [--dry-run] NODE...` | Where `kubectl` reaches the cluster | Adds the labels and taints of a Firecracker node (`onyx.app/workload=sandbox`, `onyx.app/kvm=true`, taints `workload=sandbox:NoSchedule`, `onyx.app/kvm=true:NoSchedule`). `--pod-sandbox`: the pod sandbox node labels and taint only. |

The default data dir is `/var/lib/craft-fc`, the chart default of `craft.hostAgent.dataDir`.

`apply` never erases data. It refuses a device that has a file system other than XFS, and a device that is mounted
somewhere else, and a data dir that is not empty (a mount would hide its files). For a disk already mounted at the
data dir, it checks that the disk is XFS and adds the missing fstab entry. It refuses an fstab entry that mounts
another disk at the data dir, or that has `noauto`. It cannot turn on cgroup v2 or VT-x: `check` names the fix.

Without reflink in the data dir (ext4, or XFS made without `reflink=1`), `check` prints a `WARN` when
`/dev/loop-control` exists, the same result as the chart preflight check. The host agent then makes its own sparse XFS
loop store (`<data dir>/.craft-fc-store.img`). Without `/dev/loop-control`, `check` fails. An XFS disk with reflink
(`--xfs-device`) is faster than the loop store.

## Tests

The script was run in a privileged `debian:trixie-slim` container with `xfsprogs` and `e2fsprogs`: `check`, `apply
--dry-run`, `apply --xfs-device` on a loop device (format, fstab line, mount, second run makes no change), a refused
ext4 device, a hand-mounted XFS disk and a hand-mounted ext4 disk, conflicting and `noauto` fstab entries, and
`label --dry-run`. The data dir check: XFS with reflink passes; XFS without reflink and ext4 warn with
`/dev/loop-control` and fail without it. Run `shellcheck craft-fc-node-prep.sh` after a change.
