#!/usr/bin/env bash
# Checks a built host agent image.
# Usage: check-image.sh <image ref>
#
# - host-agent runs (--help).
# - nsenter is on PATH.
# - mkfs.ext4 is on PATH and supports -d (managed drive images).
# - /opt/craft-fc passes deployment/craft-fc/check-artifacts.sh.
# - firecracker and jailer match the SHA256 pins that the agent checks at start
#   (internal/binaries/binaries.go), so the agent does not refuse them.
set -euo pipefail

image="${1:?usage: check-image.sh <image ref>}"
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "${here}/.." && pwd)"
binaries_go="${here}/internal/binaries/binaries.go"
failed=0

pass() { echo "PASS $*"; }
fail() {
  echo "FAIL $*" >&2
  failed=1
}

run() { docker run --rm --platform linux/amd64 --entrypoint "$1" "${image}" "${@:2}"; }

# The Go flag package prints the usage and exits 0 on --help.
if help="$(run /usr/local/bin/host-agent --help 2>&1)" && grep -q -- '-data-dir' <<<"${help}"; then
  pass "host-agent --help"
else
  fail "host-agent --help: ${help}"
fi

if run nsenter --version >/dev/null; then
  pass "nsenter"
else
  fail "nsenter is not on PATH"
fi

# Builds a small image from a directory, as the managed drive build does.
if run sh -c 'mkdir -p /tmp/d && echo ok >/tmp/d/f && mkfs.ext4 -q -F -d /tmp/d /tmp/i.ext4 4M' >/dev/null; then
  pass "mkfs.ext4 -d"
else
  fail "mkfs.ext4 -d does not work (e2fsprogs)"
fi

export_dir="$(mktemp -d)"
trap 'rm -rf "${export_dir}"' EXIT
cid="$(docker create --platform linux/amd64 "${image}")"
docker cp "${cid}:/opt/craft-fc" "${export_dir}/craft-fc"
docker rm "${cid}" >/dev/null

if bash "${repo}/deployment/craft-fc/check-artifacts.sh" "${export_dir}"; then
  pass "/opt/craft-fc artifacts"
else
  fail "/opt/craft-fc artifacts"
fi

# macOS has shasum, not sha256sum.
sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

for bin in firecracker jailer; do
  const="FirecrackerSHA256"
  [ "${bin}" = jailer ] && const="JailerSHA256"
  want="$(sed -n "s/^[[:space:]]*${const}[[:space:]]*= \"\([0-9a-f]*\)\"/\1/p" "${binaries_go}")"
  got="$(sha256_of "${export_dir}/craft-fc/${bin}")"
  if [ -n "${want}" ] && [ "${got}" = "${want}" ]; then
    pass "${bin} sha256 matches ${const}"
  else
    fail "${bin} sha256 ${got} does not match ${const} (${want:-not found})"
  fi
done

if [ "${failed}" -ne 0 ]; then
  echo "RESULT: FAIL" >&2
  exit 1
fi
echo "RESULT: PASS"
