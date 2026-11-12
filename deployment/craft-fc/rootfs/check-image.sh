#!/usr/bin/env bash
# Builds and checks the root drive image (Dockerfile.image).
#
#   check-image.sh                      Self-test with a small test drive (CI on pull requests).
#   check-image.sh --context-from OUT CTX
#                                       Make the build context CTX from a build-rootfs.sh
#                                       output directory OUT (built without --ca).
#   check-image.sh --image REF          Run the install of image REF into a temporary
#                                       directory and check the result.
#
# Host tools: Docker, e2fsprogs (debugfs, mkfs.ext4), file, sha256sum, python3.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
applets="cmp mkdir dirname rm cp grep tail cut sha256sum chmod sync mv sh"

# make_context OUT CTX: the files of Dockerfile.image.
make_context() {
  local out=$1 ctx=$2
  mkdir -p "${ctx}"
  python3 - "${out}/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
assert m["kind"] == "craft-fc-rootfs" and m["schema"] == 1, "not a build-rootfs.sh manifest"
assert m["build_inputs"]["egress_ca"] is None, "the published root drive must have no egress CA (build without --ca)"
assert m["guest"]["egress"]["ca_install"] == "runtime", m["guest"]["egress"]
PY
  cp --sparse=always "${out}/rootfs.ext4" "${ctx}/rootfs.ext4"
  cp "${out}/manifest.json" "${ctx}/manifest.json"
  cp "${here}/install-rootfs.sh" "${ctx}/install-rootfs.sh"
  cp "${here}/Dockerfile.image" "${ctx}/Dockerfile.image"
  rm -f "${ctx}/busybox"
  debugfs -R "dump /craft-fc/bin/busybox ${ctx}/busybox" "${ctx}/rootfs.ext4" >/dev/null 2>&1
  chmod 0755 "${ctx}/busybox" "${ctx}/install-rootfs.sh"
  case "$(file -b "${ctx}/busybox")" in
    *x86-64*"statically linked"*) ;;
    *)
      echo "busybox from the root drive is not a static x86-64 program" >&2
      exit 1
      ;;
  esac
  local list
  list=$("${ctx}/busybox" --list)
  for a in ${applets}; do
    grep -qx "${a}" <<<"${list}" || {
      echo "busybox has no ${a} applet; install-rootfs.sh needs it" >&2
      exit 1
    }
  done
  echo "context ready in ${ctx}"
}

# remove_install DIR REF: the image writes as root, so remove its files with
# its own busybox. A missing DIR is skipped (docker would make it as root).
remove_install() {
  local dir=$1 ref=$2
  [ -d "${dir}" ] || return 0
  docker run --rm --platform linux/amd64 -v "${dir}:${dir}" --entrypoint /craft-fc-rootfs/busybox "${ref}" \
    rm -rf "${dir}/rootfs" >/dev/null 2>&1 || true
  rm -rf "${dir}"
}

# check_image REF: install into an empty directory, then again (no copy).
check_image() {
  local ref=$1 dir
  dir="$(mktemp -d)"
  # A RETURN trap stays set after the function returns, so it clears itself.
  # shellcheck disable=SC2064 # expand now: dir and ref are local.
  trap "trap - RETURN; remove_install '${dir}' '${ref}'" RETURN
  docker run --rm --platform linux/amd64 -v "${dir}:${dir}" "${ref}" "${dir}/rootfs" | tee "${dir}/log1"
  grep -q "installed in ${dir}/rootfs" "${dir}/log1"
  python3 - "${dir}/rootfs" <<'PY'
import hashlib, json, os, sys
d = sys.argv[1]
m = json.load(open(os.path.join(d, "manifest.json")))
h = hashlib.sha256()
with open(os.path.join(d, "rootfs.ext4"), "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
        h.update(b)
assert h.hexdigest() == m["output"]["sha256"], "installed rootfs.ext4 does not match the manifest"
assert sorted(os.listdir(d)) == ["manifest.json", "rootfs.ext4"], os.listdir(d)
assert not os.path.exists(d + ".new") and not os.path.exists(d + ".old")
PY
  docker run --rm --platform linux/amd64 -v "${dir}:${dir}" "${ref}" "${dir}/rootfs" | tee "${dir}/log2"
  grep -q "root drive is current" "${dir}/log2"
  echo "image ${ref}: install checked"
}

self_test() {
  local work iid
  work="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '${work}'; docker image rm -f craft-fc-rootfs-check:local >/dev/null 2>&1 || true" EXIT
  # The busybox of the converter (Debian busybox-static), in a small drive.
  mkdir -p "${work}/tree/craft-fc/bin" "${work}/out"
  docker run --rm --platform linux/amd64 -v "${work}/tree/craft-fc/bin:/out" \
    "${BASE_IMAGE_REGISTRY:-docker.io}/library/debian:trixie-slim" sh -c \
    'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq --no-install-recommends busybox-static >/dev/null && cp /bin/busybox /out/busybox'
  truncate -s 64M "${work}/out/rootfs.ext4"
  mkfs.ext4 -q -F -L craft-root -d "${work}/tree" "${work}/out/rootfs.ext4"
  sum=$(sha256sum "${work}/out/rootfs.ext4" | cut -d' ' -f1)
  cat >"${work}/out/manifest.json" <<EOF
{
  "schema": 1,
  "kind": "craft-fc-rootfs",
  "build_inputs": {"egress_ca": null, "files_sha256": {"craft-init": "$(printf '%064d' 1)"}},
  "guest": {"busybox": {"sha256": "$(printf '%064d' 2)"}, "egress": {"ca_install": "runtime"}},
  "output": {"file": "rootfs.ext4", "sha256": "${sum}"}
}
EOF
  make_context "${work}/out" "${work}/ctx"
  docker build --quiet --platform linux/amd64 -f "${work}/ctx/Dockerfile.image" -t craft-fc-rootfs-check:local "${work}/ctx" >/dev/null
  check_image craft-fc-rootfs-check:local

  # A drive that does not match its manifest is not installed.
  sed -i "s/${sum}/$(printf '%064d' 3)/" "${work}/ctx/manifest.json"
  iid=$(docker build --quiet --platform linux/amd64 -f "${work}/ctx/Dockerfile.image" "${work}/ctx")
  mkdir -p "${work}/bad"
  if docker run --rm --platform linux/amd64 -v "${work}/bad:${work}/bad" "${iid}" "${work}/bad/rootfs"; then
    echo "a drive with a wrong SHA256 was installed" >&2
    exit 1
  fi
  [ ! -e "${work}/bad/rootfs" ] && [ ! -e "${work}/bad/rootfs.new" ]
  docker image rm -f "${iid}" >/dev/null
  echo "self-test passed"
}

case "${1:-}" in
  "") self_test ;;
  --context-from) make_context "${2:?OUT}" "${3:?CTX}" ;;
  --image) check_image "${2:?REF}" ;;
  *)
    echo "usage: check-image.sh [--context-from OUT CTX | --image REF]" >&2
    exit 2
    ;;
esac
