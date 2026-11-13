#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ] || [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ] || [ "$(id -u)" -ne 0 ]; then
  echo "Usage: sudo bash deployment/craft-runtime/check-kvm.sh IMAGE ARTIFACTS_DIR (Linux x86-64, root)" >&2
  exit 2
fi
[ -c /dev/kvm ] || { echo "KVM is required; /dev/kvm is absent" >&2; exit 1; }
artifacts="$(cd "$2" && pwd)"
for item in firecracker vmlinux; do test -f "$artifacts/$item"; done
repo="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
cleanup() {
  result=$?
  # Go test timeout panics do not run t.Cleanup.
  python3 - "$work/vms" "$artifacts/firecracker" <<'PYTHON' || true
import os
import signal
import sys

root, binary = sys.argv[1:]
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        process = "/proc/" + entry
        if not os.readlink(process + "/cwd").startswith(root + "/") or os.readlink(process + "/exe") != binary:
            continue
        descriptor = os.pidfd_open(int(entry))
        try:
            if os.readlink(process + "/cwd").startswith(root + "/") and os.readlink(process + "/exe") == binary:
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        finally:
            os.close(descriptor)
    except OSError:
        pass
PYTHON
  if [ "$result" -ne 0 ]; then
    while IFS= read -r log; do
      echo "Guest console: $log" >&2
      tail -80 "$log" >&2
    done < <(find "$work/vms" -name console.log 2>/dev/null || true)
  fi
  rm -rf "$work"
  exit "$result"
}
trap cleanup EXIT

uname -a
"$artifacts/firecracker" --version
# The daemon, init and harness tests kill the daemon, remount drives and read
# root-only state: the test drive runs commands as root. The host agent KVM
# lane checks the default (commands as the sandbox user).
ROOTFS_DAEMON_CMD="/craft-fc/bin/guest-daemon --command-user=" \
  bash "$repo/deployment/craft-runtime/check-rootfs.sh" "$1" "$work/images"
cp "$artifacts/vmlinux" "$work/images/vmlinux"
truncate -s 1G "$work/images/scratch-empty.ext4"
mkfs.ext4 -q -F -m 0 "$work/images/scratch-empty.ext4"
truncate -s 64M "$work/images/managed-empty.ext4"
mkfs.ext4 -q -F -m 0 "$work/images/managed-empty.ext4"
(
  cd "$repo/microvm"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go test -c -buildvcs=false -tags kvm \
    -o "$work/runtime-kvm.test" ./internal/guestd/kvmtest
)
KVM_RUNTIME_IMAGE=1 KVM_FC_BIN="$artifacts/firecracker" \
  KVM_IMG_DIR="$work/images" KVM_WORK_DIR="$work/vms" KVM_VMS=2 \
  KVM_RELAY_BIN="$work/images/egress-relay" \
  "$work/runtime-kvm.test" -test.v -test.timeout=15m \
  -test.run '^(TestDaemonKVM|TestRestoreKVM|TestInitKVM|TestRuntimeImageKVM|TestHarnessContractKVM|TestCollectKeepsPartialOutput)$'
