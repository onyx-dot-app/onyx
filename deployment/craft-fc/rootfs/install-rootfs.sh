#!/craft-fc-rootfs/busybox sh
# Copies the root drive of the rootfs image (Dockerfile.image) into DIR, the
# host agent's --rootfs-dir. The Helm chart runs it as an init container of
# the agent DaemonSet. It does nothing when DIR already has this
# build (same manifest.json).
#
# Usage: install-rootfs.sh DIR
set -eu
bb=/craft-fc-rootfs/busybox
src=/craft-fc-rootfs
dst=${1:?usage: install-rootfs.sh DIR}

if [ -f "${dst}/rootfs.ext4" ] && "${bb}" cmp -s "${src}/manifest.json" "${dst}/manifest.json"; then
  echo "root drive is current in ${dst}"
  exit 0
fi

# The agent reads the files only at start-up and on BuildTemplate, and a
# template has its own copy. Still, put the new files in place in one rename.
"${bb}" mkdir -p "$("${bb}" dirname "${dst}")"
tmp="${dst}.new"
"${bb}" rm -rf "${tmp}" "${dst}.old"
"${bb}" mkdir -m 0755 "${tmp}"
"${bb}" cp "${src}/rootfs.ext4" "${tmp}/rootfs.ext4"
# The output SHA256 is the last "sha256" in the manifest (the "output" object).
want=$("${bb}" grep -o '"sha256": "[0-9a-f]*"' "${src}/manifest.json" | "${bb}" tail -n 1 | "${bb}" cut -d'"' -f4)
got=$("${bb}" sha256sum "${tmp}/rootfs.ext4" | "${bb}" cut -d' ' -f1)
if [ -z "${want}" ] || [ "${want}" != "${got}" ]; then
  echo "rootfs.ext4 has SHA256 ${got}, the manifest has ${want}" >&2
  "${bb}" rm -rf "${tmp}"
  exit 1
fi
"${bb}" cp "${src}/manifest.json" "${tmp}/manifest.json"
"${bb}" chmod 0644 "${tmp}/rootfs.ext4" "${tmp}/manifest.json"
"${bb}" sync
if [ -e "${dst}" ]; then
  "${bb}" mv "${dst}" "${dst}.old"
fi
"${bb}" mv "${tmp}" "${dst}"
"${bb}" rm -rf "${dst}.old"
echo "root drive ${got} installed in ${dst}"
