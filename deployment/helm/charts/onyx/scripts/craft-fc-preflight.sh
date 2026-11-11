#!/bin/sh
# Checks whether this node can run Craft Firecracker sandboxes.
# Rendered into the craft-fc-preflight ConfigMap. POSIX sh; needs awk, grep
# and GNU coreutils (`cp --reflink`, `stat -f`, `mktemp`).
#
# Env:
#   NODE_NAME           node name, for the log header
#   SCRATCH_DIR         writable dir on the node's sandbox data filesystem
#   SCRATCH_HOST_PATH   host path of SCRATCH_DIR, for messages
#   MIN_MAX_MAP_COUNT   required vm.max_map_count (default 1048576)
#   MIN_FREE_DISK_GIB   free space below this is a WARN (default 50)

SCRATCH_DIR="${SCRATCH_DIR:-/scratch}"
SCRATCH_HOST_PATH="${SCRATCH_HOST_PATH:-$SCRATCH_DIR}"
MIN_MAX_MAP_COUNT="${MIN_MAX_MAP_COUNT:-1048576}"
MIN_FREE_DISK_GIB="${MIN_FREE_DISK_GIB:-50}"

fails=0
warns=0

pass() { echo "PASS  $1: $2"; }
warn() { echo "WARN  $1: $2"; warns=$((warns + 1)); }
fail() { echo "FAIL  $1: $2"; fails=$((fails + 1)); }

check_kvm() {
	if [ ! -e /dev/kvm ]; then
		fail kvm "/dev/kvm does not exist. Use a metal instance, or enable nested virtualization on the node pool."
		return
	fi
	if err=$( (exec 3<>/dev/kvm) 2>&1); then
		pass kvm "/dev/kvm opens read-write"
	else
		fail kvm "/dev/kvm exists but does not open (${err##*: }). Run privileged, or set craft.firecrackerPreflight.kvmDeviceResource."
	fi
}

check_cpu() {
	vendor=$(awk -F': *' '/^vendor_id/ {print $2; exit}' /proc/cpuinfo)
	if [ "$vendor" = "GenuineIntel" ]; then
		pass cpu-vendor "$vendor"
	else
		fail cpu-vendor "${vendor:-unknown} ($(uname -m)). Craft Firecracker supports Intel nodes only."
	fi
	if grep -qw vmx /proc/cpuinfo; then
		pass cpu-vmx "VT-x (vmx) is exposed to this node"
	else
		fail cpu-vmx "no vmx CPU flag. Nested virtualization is off for this node."
	fi
}

check_cgroup() {
	if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
		pass cgroup "cgroup v2"
	else
		fail cgroup "/sys/fs/cgroup is not cgroup v2. Use a node image with the unified cgroup hierarchy."
	fi
}

check_kernel() {
	release=$(uname -r)
	series=$(echo "$release" | cut -d. -f1-2)
	case "$series" in
	5.10 | 6.1 | 6.18) pass kernel "$release" ;;
	*) warn kernel "$release is not a Firecracker-tested host kernel (5.10, 6.1, 6.18)" ;;
	esac
}

check_max_map_count() {
	value=$(cat /proc/sys/vm/max_map_count 2>/dev/null)
	if [ -z "$value" ]; then
		fail max-map-count "cannot read /proc/sys/vm/max_map_count"
	elif [ "$value" -ge "$MIN_MAX_MAP_COUNT" ]; then
		pass max-map-count "$value"
	else
		fail max-map-count "$value, need >= $MIN_MAX_MAP_COUNT. Set the vm.max_map_count sysctl on the node pool."
	fi
}

check_filesystem() {
	fstype=$(stat -f -c %T "$SCRATCH_DIR" 2>/dev/null)
	if ! probe=$(mktemp -d "$SCRATCH_DIR/reflink-probe.XXXXXX" 2>&1); then
		fail filesystem "$SCRATCH_HOST_PATH is not writable or full (${probe##*: })"
		return
	fi
	if ! err=$(dd if=/dev/zero of="$probe/a" bs=64k count=16 2>&1 >/dev/null); then
		err=$(echo "$err" | grep -m 1 '^dd:')
		fail filesystem "$SCRATCH_HOST_PATH is not writable or full (${err##*: })"
	elif [ "$fstype" != "xfs" ]; then
		warn filesystem "$SCRATCH_HOST_PATH is '${fstype:-unknown}', not XFS. The host agent will use an XFS loop file."
	elif err=$(cp --reflink=always "$probe/a" "$probe/b" 2>&1); then
		pass filesystem "$SCRATCH_HOST_PATH is XFS with reflink"
	else
		fail filesystem "$SCRATCH_HOST_PATH is XFS without reflink (${err##*: }). Format it with 'mkfs.xfs -m reflink=1'."
	fi
	rm -rf "$probe"
}

check_free_disk() {
	avail_kib=$(df -Pk "$SCRATCH_DIR" 2>/dev/null | awk 'NR == 2 {print $4}')
	if [ -z "$avail_kib" ]; then
		fail free-disk "cannot read free space of $SCRATCH_HOST_PATH"
		return
	fi
	avail_gib=$((avail_kib / 1048576))
	if [ "$avail_gib" -ge "$MIN_FREE_DISK_GIB" ]; then
		pass free-disk "${avail_gib} GiB free on $SCRATCH_HOST_PATH"
	else
		warn free-disk "${avail_gib} GiB free on $SCRATCH_HOST_PATH, below ${MIN_FREE_DISK_GIB} GiB"
	fi
}

echo "Craft Firecracker preflight on node ${NODE_NAME:-unknown}"
check_kvm
check_cpu
check_cgroup
check_kernel
check_max_map_count
check_filesystem
check_free_disk

if [ "$fails" -gt 0 ]; then
	echo "RESULT: FAIL ($fails failed, $warns warnings) on node ${NODE_NAME:-unknown}"
else
	echo "RESULT: PASS ($warns warnings) on node ${NODE_NAME:-unknown}"
fi
