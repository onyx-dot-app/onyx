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
# 2. Managed mounts (MANAGED_MOUNTS: skills, user-uploads, spaces): slot A
#    of each (ext4, Firecracker is_read_only) is mounted read-only and noexec
#    on /mnt/<name>, with private propagation. The device itself is
#    read-only, so root in the guest cannot write to it, also not after a
#    remount. With no device, an empty read-only tmpfs goes there, so the
#    path is never writable. Slot B is a spare for a live update; attach
#    never mounts it (see README.md).
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
MANAGED_MOUNTS="skills:/mnt/skills:/dev/vdc:/dev/vdf"
SCRATCH_MNT=/mnt/scratch
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
# managed_mount <name:mount point:slot A:slot B>: sets m_name, m_mnt, m_a, m_b.
managed_mount() {
  m_name=${1%%:*}
  rest=${1#*:}
  m_mnt=${rest%%:*}
  rest=${rest#*:}
  m_a=${rest%%:*}
  m_b=${rest#*:}
  case "${m_mnt}" in
    /mnt/?*) ;;
    *)
      log "managed mount ${m_name}: ${m_mnt} is not below /mnt"
      exit 1
      ;;
  esac
}

# A writable managed drive is a host configuration error. Do not mount it.
# Missing devices are fine: older templates do not have them.
for m in ${MANAGED_MOUNTS}; do
  managed_mount "${m}"
  for dev in "${m_a}" "${m_b}"; do
    if [ -b "${dev}" ] && [ "$(dev_ro "${dev}")" != 1 ]; then
      log "${dev} is not a read-only drive"
      exit 1
    fi
  done
done

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

# The mount points are on the read-only root (build-rootfs.sh makes them).
mounted=""
for m in ${MANAGED_MOUNTS}; do
  managed_mount "${m}"
  [ -d "${m_mnt}" ] || {
    log "no mount point ${m_mnt}"
    exit 1
  }
  if is_mnt "${m_mnt}"; then
    log "${m_mnt} already mounted"
  else
    if [ -b "${m_a}" ]; then
      mount -t ext4 -o ro,noload,nodev,nosuid,noexec "${m_a}" "${m_mnt}"
    else
      log "no managed drive ${m_a}; ${m_mnt} is an empty read-only tmpfs"
      mount -t tmpfs -o ro,nodev,nosuid,noexec,size=4k,mode=0755 "craft-${m_name}-empty" "${m_mnt}"
    fi
    # Private: an update mounts slot B beneath this mount and then detaches
    # this one (README.md). Those events must stay local.
    mount --make-private "${m_mnt}"
  fi
  mounted="${mounted} ${m_mnt}"
done

: >/run/craft-fc/attached
log "attached ${SCRATCH_DEV} (${OVERLAY_DIRS}) and${mounted}"
