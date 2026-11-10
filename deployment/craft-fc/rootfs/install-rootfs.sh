#!/bin/sh
# Init container entrypoint of the craft-fc-rootfs image (push-dev-ecr.sh rootfs).
# Copies rootfs.ext4, manifest.json and egress-ca.crt into the host agent's
# --rootfs-dir on the node. Usage: install-rootfs [DEST], default
# /var/lib/craft-fc/rootfs.
#
# The agent reads the directory at start. manifest.json is moved in last, so
# the agent never sees a manifest without its root drive. Does nothing when
# DEST already has this manifest.
set -eu

src=/craft-fc-rootfs
dest="${1:-/var/lib/craft-fc/rootfs}"

mkdir -p "${dest}"
chmod 0700 "${dest}"
if cmp -s "${src}/manifest.json" "${dest}/manifest.json" &&
  cmp -s "${src}/egress-ca.crt" "${dest}/egress-ca.crt" &&
  [ -f "${dest}/rootfs.ext4" ]; then
  echo "install-rootfs: ${dest} is current"
  exit 0
fi

tmp="${dest}/.incoming"
rm -rf "${tmp}"
mkdir -m 0700 "${tmp}"
cp --sparse=always "${src}/rootfs.ext4" "${tmp}/rootfs.ext4"
(cd "${tmp}" && sha256sum -c "${src}/rootfs.ext4.sha256")
cp "${src}/manifest.json" "${src}/egress-ca.crt" "${tmp}/"
chmod 0644 "${tmp}/rootfs.ext4" "${tmp}/manifest.json" "${tmp}/egress-ca.crt"

# The agent reads the manifest first: remove it first, add it last.
rm -f "${dest}/manifest.json"
mv -f "${tmp}/rootfs.ext4" "${dest}/rootfs.ext4"
mv -f "${tmp}/egress-ca.crt" "${dest}/egress-ca.crt"
mv -f "${tmp}/manifest.json" "${dest}/manifest.json"
rmdir "${tmp}"
echo "install-rootfs: installed into ${dest}"
