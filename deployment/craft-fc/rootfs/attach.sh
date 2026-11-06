#!/craft-fc/bin/busybox sh
# shellcheck shell=dash
# Attaches the per-VM drives. Installed as /craft-fc/lib/attach; runs as root.
#
# craft-init runs it at boot. With craft.scratch=defer (template boots) the
# guest daemon runs it after a snapshot restore, when the host has put this
# VM's own scratch and managed files behind the drives.
#
# 1. Scratch drive (read-write ext4): mounted on /mnt/scratch. Each directory
#    in OVERLAY_DIRS gets an overlay: the read-only root is the lower layer,
#    the upper layer is on the scratch disk. A saved scratch disk therefore
#    holds only the user's changes, and can go on top of a new template.
# 2. Managed drive (ext4, Firecracker is_read_only): mounted read-only on
#    /workspace/managed. The device itself is read-only, so root in the guest
#    cannot write to it, also not after a remount. With no managed drive, an
#    empty read-only tmpfs goes there, so the path is never writable.
#
# It runs in the static busybox shell on the read-only root, and busybox runs
# every command in this script itself (no PATH lookup). Once the /usr and /etc
# overlays are mounted, no program or library from them may run as root here.
#
# Running it a second time does nothing.
set -euo pipefail
# shellcheck disable=SC2123 # intended: no command may come from PATH.
PATH=/nonexistent

SCRATCH_DEV=/dev/vdb
MANAGED_DEV=/dev/vdc
SCRATCH_MNT=/mnt/scratch
MANAGED_MNT=/workspace/managed
OVERLAY_DIRS="/etc /home /root /opt /srv /usr /var /workspace"
LAYOUT_VERSION=1
CRAFT=/craft-fc

log() { echo "attach: $*" >&2; }

# Programs that init restarts live in /craft-fc. It must stay on the read-only
# root: never under an overlay, never on a writable mount. Check this before
# reading any file from it. The probe write fails with EROFS there.
if (: >"${CRAFT}/.rw-probe") 2>/dev/null; then
  rm -f "${CRAFT}/.rw-probe"
  log "${CRAFT} is on a writable mount"
  exit 1
fi
# shellcheck source=/dev/null
[ -r "${CRAFT}/etc/init.conf" ] && . "${CRAFT}/etc/init.conf"
# shellcheck disable=SC2123
PATH=/nonexistent
for dir in ${OVERLAY_DIRS}; do
  case "${dir}" in
    / | "${CRAFT}" | "${CRAFT}"/*)
      log "OVERLAY_DIRS must not cover ${CRAFT}: ${dir}"
      exit 1
      ;;
  esac
done

dev_ro() { cat "/sys/block/${1##*/}/ro"; }
# is_mnt <dir>: true if dir is a mount point (paths here have no spaces).
is_mnt() { grep -q "^[^ ]* $1 " /proc/self/mounts; }

if [ -e /run/craft-fc/attached ]; then
  log "already attached"
  exit 0
fi

[ -b "${SCRATCH_DEV}" ] || {
  log "no scratch drive ${SCRATCH_DEV}"
  exit 1
}
[ "$(dev_ro "${SCRATCH_DEV}")" = 0 ] || {
  log "${SCRATCH_DEV} is read-only"
  exit 1
}
if [ -b "${MANAGED_DEV}" ] && [ "$(dev_ro "${MANAGED_DEV}")" != 1 ]; then
  # A writable managed drive is a host configuration error. Do not mount it.
  log "${MANAGED_DEV} is not a read-only drive"
  exit 1
fi

# The template guest may have cached blocks of the template's scratch file.
blockdev --flushbufs "${SCRATCH_DEV}"
is_mnt "${SCRATCH_MNT}" || mount -t ext4 -o noatime,nodev "${SCRATCH_DEV}" "${SCRATCH_MNT}"

layout="${SCRATCH_MNT}/.craft-layout"
if [ -f "${layout}" ]; then
  have=$(cat "${layout}")
  [ "${have}" = "${LAYOUT_VERSION}" ] || {
    log "scratch layout ${have}, want ${LAYOUT_VERSION}"
    exit 1
  }
else
  echo "${LAYOUT_VERSION}" >"${layout}"
fi

for dir in ${OVERLAY_DIRS}; do
  [ -d "${dir}" ] || continue
  is_mnt "${dir}" && continue
  name=$(echo "${dir#/}" | tr / _)
  upper="${SCRATCH_MNT}/overlay/${name}/upper"
  work="${SCRATCH_MNT}/overlay/${name}/work"
  if [ ! -d "${upper}" ]; then
    mkdir -p "${upper}" "${work}"
    # The merged directory shows the owner and mode of the upper directory.
    chown "$(stat -c %u:%g "${dir}")" "${upper}"
    chmod "$(stat -c %a "${dir}")" "${upper}"
  fi
  mount -t overlay overlay -o "lowerdir=${dir},upperdir=${upper},workdir=${work}" "${dir}"
done

mkdir -p "${MANAGED_MNT}"
if is_mnt "${MANAGED_MNT}"; then
  log "${MANAGED_MNT} already mounted"
elif [ -b "${MANAGED_DEV}" ]; then
  mount -t ext4 -o ro,noload,nodev,nosuid "${MANAGED_DEV}" "${MANAGED_MNT}"
else
  log "no managed drive ${MANAGED_DEV}; ${MANAGED_MNT} is an empty read-only tmpfs"
  mount -t tmpfs -o ro,nodev,nosuid,noexec,size=4k,mode=0755 craft-managed-empty "${MANAGED_MNT}"
fi

: >/run/craft-fc/attached
log "attached ${SCRATCH_DEV} (${OVERLAY_DIRS}) and ${MANAGED_MNT}"
