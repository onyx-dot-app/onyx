#!/usr/bin/env bash
# Checks an exported craft-fc-artifacts image tree.
# Usage: check-artifacts.sh <dir containing craft-fc/>
#
# - vmlinux is an x86_64 ELF file with the kernel release from KERNEL_TAG.
# - vmlinux.config has every line of kernel/config-fragment.
# - firecracker and jailer match the SHA256SUMS of the upstream release. The
#   release tarball is downloaded again here, so this does not trust the build.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="${1:?usage: check-artifacts.sh <export dir>}/craft-fc"
fc_version="$(sed -n 's/^ARG FC_VERSION=//p' "${here}/Dockerfile.artifacts")"
fc_tarball_sha256="$(sed -n 's/^ARG FC_TARBALL_SHA256=//p' "${here}/Dockerfile.artifacts")"
kernel_tag="$(sed -n 's/^ARG KERNEL_TAG=//p' "${here}/Dockerfile.artifacts")"
kernel_release="$(sed -E 's/^(microvm-)?kernel[0-9.]*-//' <<<"${kernel_tag}")"
kernel_release="${kernel_release%%-*}"
fragment="${here}/kernel/config-fragment"
failed=0

pass() { echo "PASS $*"; }
fail() {
  echo "FAIL $*" >&2
  failed=1
}
sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

for f in vmlinux vmlinux.config firecracker jailer SOURCE.md \
  licenses/linux/COPYING licenses/linux/GPL-2.0 licenses/linux/Linux-syscall-note \
  licenses/firecracker/LICENSE licenses/firecracker/NOTICE licenses/firecracker/THIRD-PARTY; do
  if [ -s "${root}/${f}" ]; then pass "${f} exists"; else fail "${f} is missing or empty"; fi
done

# ELF magic, ELFCLASS64 and e_machine EM_X86_64 (0x3e).
header="$(od -An -tx1 -N20 "${root}/vmlinux" | tr -d ' \n')"
if [ "${header:0:10}" = "7f454c4602" ] && [ "${header:36:4}" = "3e00" ]; then
  pass "vmlinux is an x86_64 ELF file"
else
  fail "vmlinux is not an x86_64 ELF file (header ${header})"
fi

# The banner has the release, then " (" and the build user.
if LC_ALL=C grep -aqF "Linux version ${kernel_release} (" "${root}/vmlinux"; then
  pass "vmlinux is kernel release ${kernel_release}"
else
  fail "vmlinux is not kernel release ${kernel_release}"
fi

checked=0
if [ -s "${fragment}" ]; then
  while IFS= read -r line; do
    checked=$((checked + 1))
    if grep -qxF "${line}" "${root}/vmlinux.config"; then
      pass "config: ${line}"
    else
      fail "config does not have: ${line}"
    fi
  done < <(grep -E '^(CONFIG_[A-Z0-9_]+=|# CONFIG_[A-Z0-9_]+ is not set$)' "${fragment}" || true)
fi
if [ "${checked}" -eq 0 ]; then
  fail "kernel/config-fragment is missing or has no config lines"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
tgz="firecracker-${fc_version}-x86_64.tgz"
curl -fsSL -o "${tmp}/${tgz}" "https://github.com/firecracker-microvm/firecracker/releases/download/${fc_version}/${tgz}"
if [ "$(sha256 "${tmp}/${tgz}")" = "${fc_tarball_sha256}" ]; then
  pass "${tgz} matches the pinned SHA256"
else
  fail "${tgz} does not match the pinned SHA256"
fi
tar -xzf "${tmp}/${tgz}" -C "${tmp}" "release-${fc_version}-x86_64/SHA256SUMS"
for bin in firecracker jailer; do
  want="$(awk -v f="./${bin}-${fc_version}-x86_64" '$2 == f { print $1 }' "${tmp}/release-${fc_version}-x86_64/SHA256SUMS")"
  got="$(sha256 "${root}/${bin}")"
  if [ -n "${want}" ] && [ "${want}" = "${got}" ]; then
    pass "${bin} matches the ${fc_version} release SHA256SUMS"
  else
    fail "${bin} SHA256 ${got} does not match the release (${want:-not listed})"
  fi
done

if [ "${failed}" -ne 0 ]; then
  echo "One or more checks failed." >&2
  exit 1
fi
echo "All checks passed."
