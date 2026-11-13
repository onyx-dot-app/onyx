#!/usr/bin/env bash
# Checks and prepares a Kubernetes node for Craft Firecracker sandboxes.
# Customer guide: https://docs.onyx.app/deployment/kubernetes/craft-firecracker-bare-metal
#
#   craft-fc-node-prep.sh check [--data-dir DIR]
#   craft-fc-node-prep.sh apply [--data-dir DIR] [--xfs-device DEV] [--dry-run]
#   craft-fc-node-prep.sh label --context CTX [--pod-sandbox] [--dry-run] NODE...
#
# check and apply run on the node, apply as root. label runs where kubectl
# reaches the cluster.
set -euo pipefail

DATA_DIR=/var/lib/craft-fc
MIN_MAX_MAP_COUNT=1048576
MIN_FREE_DISK_GIB=50
# zz sorts after 99-sysctl.conf, so a lower value in /etc/sysctl.conf does not win.
SYSCTL_FILE=/etc/sysctl.d/99-zz-onyx-firecracker.conf
MODULES_FILE=/etc/modules-load.d/onyx-craft-fc.conf

fails=0
warns=0
dry_run=0

pass() { echo "PASS  $1: $2"; }
warn() {
	echo "WARN  $1: $2"
	warns=$((warns + 1))
}
fail() {
	echo "FAIL  $1: $2"
	fails=$((fails + 1))
}
info() { echo "INFO  $1: $2"; }
die() {
	echo "error: $*" >&2
	exit 2
}

usage() {
	sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
	exit 2
}

# Runs a change, or prints it with --dry-run.
run() {
	if [ "$dry_run" -eq 1 ]; then
		echo "DRY   $*"
	else
		echo "RUN   $*"
		"$@"
	fi
}

# Writes stdin to a file, or prints the file with --dry-run.
write_file() {
	local path=$1 content
	content=$(cat)
	if [ "$dry_run" -eq 1 ]; then
		echo "DRY   write $path: $content"
	else
		echo "RUN   write $path"
		printf '%s\n' "$content" >"$path"
	fi
}

check_kvm() {
	if [ ! -e /dev/kvm ]; then
		fail kvm "/dev/kvm does not exist. Turn on VT-x in the BIOS and load kvm_intel (apply does this), or turn on nested virtualization for this VM."
	elif [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
		pass kvm "/dev/kvm is readable and writable"
	else
		fail kvm "/dev/kvm exists but this user cannot open it. Run as root."
	fi
}

check_cpu() {
	local vendor
	vendor=$(awk -F': *' '/^vendor_id/ {print $2; exit}' /proc/cpuinfo)
	if [ "$vendor" = "GenuineIntel" ]; then
		pass cpu-vendor "$vendor"
	else
		fail cpu-vendor "${vendor:-unknown} ($(uname -m)). Craft Firecracker supports Intel x86_64 only."
	fi
	if grep -qw vmx /proc/cpuinfo; then
		pass cpu-vmx "the vmx CPU flag is present"
	else
		fail cpu-vmx "no vmx CPU flag. Turn on VT-x in the BIOS, or nested virtualization for this VM."
	fi
}

check_cgroup() {
	if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
		pass cgroup "cgroup v2"
	else
		fail cgroup "/sys/fs/cgroup is not cgroup v2. Boot with systemd.unified_cgroup_hierarchy=1 or use a newer OS."
	fi
}

check_systemd() {
	if [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ]; then
		pass systemd "PID 1 is systemd"
	else
		fail systemd "PID 1 is '$(cat /proc/1/comm 2>/dev/null)'. The host agent runs microVMs in systemd scopes."
	fi
}

check_kernel() {
	local release series
	release=$(uname -r)
	series=$(echo "$release" | cut -d. -f1-2)
	case "$series" in
	5.10 | 6.1 | 6.18) pass kernel "$release" ;;
	*) warn kernel "$release is not a tested host kernel (5.10, 6.1, 6.18)" ;;
	esac
}

check_max_map_count() {
	local value
	value=$(cat /proc/sys/vm/max_map_count 2>/dev/null || true)
	if [ -z "$value" ]; then
		fail max-map-count "cannot read /proc/sys/vm/max_map_count"
	elif [ "$value" -ge "$MIN_MAX_MAP_COUNT" ]; then
		pass max-map-count "$value"
	else
		fail max-map-count "$value, need >= $MIN_MAX_MAP_COUNT (apply sets it)"
	fi
}

check_data_dir() {
	local fstype probe avail_kib
	if [ ! -d "$DATA_DIR" ]; then
		fail data-dir "$DATA_DIR does not exist (apply makes it)"
		return
	fi
	fstype=$(stat -f -c %T "$DATA_DIR" 2>/dev/null || echo unknown)
	if [ "$fstype" = "xfs" ]; then
		if ! probe=$(mktemp -d "$DATA_DIR/reflink-probe.XXXXXX" 2>/dev/null); then
			fail data-dir "$DATA_DIR is not writable. Run as root."
			return
		fi
		head -c 65536 /dev/zero >"$probe/a"
		if cp --reflink=always "$probe/a" "$probe/b" 2>/dev/null; then
			pass data-dir "$DATA_DIR is XFS with reflink"
		else
			fail data-dir "$DATA_DIR is XFS without reflink. Make the file system again with 'mkfs.xfs -m reflink=1'."
		fi
		rm -rf "$probe"
	elif [ -e /dev/loop-control ]; then
		info data-dir "$DATA_DIR is '$fstype'. The host agent makes an XFS loop file in it."
	else
		fail data-dir "$DATA_DIR is '$fstype' and /dev/loop-control does not exist. Load the loop module, or mount an XFS disk (apply --xfs-device)."
	fi
	avail_kib=$(df -Pk "$DATA_DIR" | awk 'NR == 2 {print $4}')
	if [ $((avail_kib / 1048576)) -ge "$MIN_FREE_DISK_GIB" ]; then
		pass free-disk "$((avail_kib / 1048576)) GiB free in $DATA_DIR"
	else
		warn free-disk "$((avail_kib / 1048576)) GiB free in $DATA_DIR, below $MIN_FREE_DISK_GIB GiB"
	fi
}

cmd_check() {
	echo "Craft Firecracker node check on $(hostname)"
	check_kvm
	check_cpu
	check_cgroup
	check_systemd
	check_kernel
	check_max_map_count
	check_data_dir
	if [ "$fails" -gt 0 ]; then
		echo "RESULT: FAIL ($fails failed, $warns warnings)"
		return 1
	fi
	echo "RESULT: PASS ($warns warnings)"
}

apply_modules() {
	local modules=()
	[ -e /dev/loop-control ] || modules+=(loop)
	if [ ! -e /dev/kvm ]; then
		if grep -qw vmx /proc/cpuinfo; then
			modules+=(kvm_intel)
		else
			echo "SKIP  kvm: no vmx CPU flag, so kvm_intel cannot load. Turn on VT-x in the BIOS, or nested virtualization for this VM."
		fi
	fi
	[ ${#modules[@]} -gt 0 ] || return 0
	run modprobe -a "${modules[@]}"
	printf '%s\n' kvm_intel loop | write_file "$MODULES_FILE"
}

apply_sysctl() {
	local value
	value=$(cat /proc/sys/vm/max_map_count)
	if [ "$value" -ge "$MIN_MAX_MAP_COUNT" ]; then
		# Keep a higher value; only make it survive a reboot.
		[ -f "$SYSCTL_FILE" ] || echo "vm.max_map_count = $value" | write_file "$SYSCTL_FILE"
		return
	fi
	echo "vm.max_map_count = $MIN_MAX_MAP_COUNT" | write_file "$SYSCTL_FILE"
	run sysctl -w "vm.max_map_count=$MIN_MAX_MAP_COUNT"
}

apply_xfs_device() {
	local dev=$1 current uuid
	[ -b "$dev" ] || die "$dev is not a block device"
	command -v mkfs.xfs >/dev/null || die "mkfs.xfs not found. Install xfsprogs."
	if findmnt -n -S "$dev" >/dev/null 2>&1; then
		[ "$(findmnt -n -o TARGET -S "$dev")" = "$DATA_DIR" ] || die "$dev is mounted somewhere else"
		return
	fi
	if [ -n "$(find "$DATA_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]; then
		die "$DATA_DIR is not empty. A mount would hide its files. Drain the node, stop the host agent and empty $DATA_DIR first."
	fi
	current=$(blkid -o value -s TYPE "$dev" 2>/dev/null || true)
	if [ -z "$current" ]; then
		run mkfs.xfs -m reflink=1 "$dev"
	elif [ "$current" != "xfs" ]; then
		die "$dev has the file system $current. This script does not erase it. Wipe it yourself, then run apply again."
	fi
	if [ "$dry_run" -eq 1 ]; then
		echo "DRY   add $dev to /etc/fstab at $DATA_DIR and mount it"
		return
	fi
	uuid=$(blkid -o value -s UUID "$dev")
	if ! grep -q "UUID=$uuid" /etc/fstab; then
		echo "UUID=$uuid $DATA_DIR xfs defaults 0 2" | write_file_append /etc/fstab
	fi
	command -v systemctl >/dev/null && run systemctl daemon-reload
	run mount "$DATA_DIR"
}

write_file_append() {
	local path=$1 line
	line=$(cat)
	echo "RUN   append to $path: $line"
	printf '%s\n' "$line" >>"$path"
}

cmd_apply() {
	local xfs_device=$1
	if [ "$dry_run" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
		die "apply needs root"
	fi
	apply_modules
	apply_sysctl
	run mkdir -p "$DATA_DIR"
	if [ -n "$xfs_device" ]; then
		apply_xfs_device "$xfs_device"
	fi
	if [ "$dry_run" -eq 1 ]; then
		return
	fi
	echo
	cmd_check
}

cmd_label() {
	local context=$1 pod_sandbox=$2
	shift 2
	[ -n "$context" ] || die "label needs --context"
	[ $# -gt 0 ] || die "label needs at least one node name"
	local k=(kubectl --context "$context")
	for node in "$@"; do
		if [ "$pod_sandbox" -eq 1 ]; then
			run "${k[@]}" label node "$node" onyx.app/workload=sandbox --overwrite
			run "${k[@]}" taint node "$node" workload=sandbox:NoSchedule --overwrite
		else
			run "${k[@]}" label node "$node" onyx.app/workload=sandbox onyx.app/kvm=true --overwrite
			run "${k[@]}" taint node "$node" workload=sandbox:NoSchedule onyx.app/kvm=true:NoSchedule --overwrite
		fi
	done
}

main() {
	[ $# -gt 0 ] || usage
	local cmd=$1 xfs_device="" context="" pod_sandbox=0
	shift
	local nodes=()
	while [ $# -gt 0 ]; do
		case "$1" in
		--data-dir)
			DATA_DIR=${2:?--data-dir needs a value}
			shift 2
			;;
		--xfs-device)
			xfs_device=${2:?--xfs-device needs a value}
			shift 2
			;;
		--context)
			context=${2:?--context needs a value}
			shift 2
			;;
		--pod-sandbox)
			pod_sandbox=1
			shift
			;;
		--dry-run)
			dry_run=1
			shift
			;;
		-h | --help) usage ;;
		-*) die "unknown option $1" ;;
		*)
			nodes+=("$1")
			shift
			;;
		esac
	done
	case "$cmd" in
	check) cmd_check ;;
	apply) cmd_apply "$xfs_device" ;;
	label) cmd_label "$context" "$pod_sandbox" "${nodes[@]+"${nodes[@]}"}" ;;
	*) usage ;;
	esac
}

main "$@"
