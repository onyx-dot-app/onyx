#!/usr/bin/env bash
# Runs the host agent KVM tests (internal/kvmtest) on one KVM host.
#
# Usage (Linux x86-64, as root, with Docker and Go):
#   check-kvm.sh smoke|full ARTIFACTS_DIR SOURCE_IMAGE
#
#   ARTIFACTS_DIR  firecracker, jailer and vmlinux (the /craft-fc tree of
#                  onyxdotapp/craft-fc-artifacts).
#   SOURCE_IMAGE   onyxdotapp/sandbox:<tag>, the source of the root drives.
#
# smoke: TestCoreKVM, TestDialKVM, TestRestartKVM, TestLoopStoreKVM (kit root
#        drive only).
# full:  smoke, then the egress, pass-through, template, managed drive,
#        memory, root drive delivery and VM cap tests. It needs KVM_PYTHON: a Python
#        with backend/requirements/default.txt (the egress proxy harness).
#
# Optional env: KVM_VMS (default 4), BASE_IMAGE_REGISTRY (a Docker Hub
# pull-through cache), KVM_ONLY (a test name regex, to run fewer tests),
# KVM_S3_BUCKET (TestSavesKVM; without it the test skips), KVM_KEEP_WORK=1.
set -euo pipefail

if [ "$#" -ne 3 ] || [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ] || [ "$(id -u)" -ne 0 ]; then
  echo "Usage: sudo bash microvm/check-kvm.sh smoke|full ARTIFACTS_DIR SOURCE_IMAGE (Linux x86-64, root)" >&2
  exit 2
fi
lane=$1
source_image=$3
case "${lane}" in smoke | full) ;; *)
  echo "lane must be smoke or full" >&2
  exit 2
  ;;
esac
[ -c /dev/kvm ] || {
  echo "KVM is required; /dev/kvm is absent" >&2
  exit 1
}
for tool in docker go mkfs.xfs mkfs.ext4 e2fsck debugfs openssl python3 file setsid; do
  command -v "${tool}" >/dev/null || {
    echo "${tool} is required" >&2
    exit 1
  }
done
artifacts="$(cd "$2" && pwd)"
for item in firecracker jailer vmlinux; do test -f "${artifacts}/${item}"; done
if [ "${lane}" = full ]; then
  [ -x "${KVM_PYTHON:-}" ] || {
    echo "the full lane needs KVM_PYTHON (a Python with backend/requirements/default.txt)" >&2
    exit 1
  }
  # Absolute, but not resolved: a venv python is a symlink.
  KVM_PYTHON="$(cd "$(dirname "${KVM_PYTHON}")" && pwd)/$(basename "${KVM_PYTHON}")"
  export KVM_PYTHON
fi
tests="TestCoreKVM TestDialKVM TestRestartKVM TestLoopStoreKVM"
if [ "${lane}" = full ]; then
  tests="${tests} TestEgressKVM TestPassthroughKVM TestSavesKVM TestTemplateBuildKVM TestManagedSwapKVM"
  tests="${tests} TestMemAdmissionKVM TestMemOOMKVM TestRootfsDeliveryKVM TestMaxVMsKVM"
fi
if [ -n "${KVM_ONLY:-}" ]; then
  selected=""
  for test in ${tests}; do
    if [[ "${test}" =~ ${KVM_ONLY} ]]; then selected="${selected} ${test}"; fi
  done
  [ -n "${selected}" ] || {
    echo "KVM_ONLY=${KVM_ONLY} selects no test of the ${lane} lane" >&2
    exit 2
  }
  tests="${selected}"
fi
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "${here}/.." && pwd)"
testdata="${here}/internal/kvmtest/testdata"
registry="${BASE_IMAGE_REGISTRY:-docker.io}"
vms="${KVM_VMS:-4}"
export BUILDX_BUILDER=default

work="$(mktemp -d /var/tmp/craft-fc-kvm.XXXXXX)"
# A short path: the jail's API socket path must fit in sun_path (108 bytes).
xfs=/mnt/fckvm
if mountpoint -q "${xfs}"; then
  echo "${xfs} is already mounted" >&2
  exit 1
fi
containers="kvm-redis ha1 ha2 ls1 ls2 ls3 pt-a1 pt-a2 tb-a1 tb-a2 ms-a1 mem-a1 mem-oom-a1 rd-a1 rd-a2 sv-a1"
cleanup_vms() {
  # A Go test timeout panic does not run t.Cleanup.
  # shellcheck disable=SC2086
  docker rm -f ${containers} >/dev/null 2>&1 || true
  # Jailed Firecracker processes have their root in the data dir.
  for proc in /proc/[0-9]*; do
    case "$(readlink "${proc}/root" 2>/dev/null)" in "${xfs}"/*) kill -KILL "${proc#/proc/}" 2>/dev/null || true ;; esac
  done
}
test_pid="" mitm=""
cleanup() {
  result=$?
  if [ -n "${test_pid}" ]; then kill -KILL -- "-${test_pid}" 2>/dev/null || true; fi
  if [ -n "${mitm}" ]; then kill -KILL "${mitm}" 2>/dev/null || true; fi
  cleanup_vms
  if [ "${KVM_KEEP_WORK:-}" != 1 ]; then
    umount "${xfs}" 2>/dev/null || true
    rm -rf "${work}"
  fi
  exit "${result}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
step() { echo "== $(date -u +%H:%M:%S) $*"; }
# show_logs DIR: the tails of the test and guest console logs under DIR.
show_logs() {
  while IFS= read -r log; do
    echo "== ${log}" >&2
    tail -60 "${log}" >&2
  done < <(find "$1" -name '*.log' 2>/dev/null | head -20 || true)
}

uname -a
"${artifacts}/firecracker" --version | head -1
mkdir -p "${work}/bin" "${work}/logs" "${xfs}"

# The agent clones template files with reflinks: XFS with reflink=1.
step "XFS data dir"
truncate -s 100G "${work}/xfs.img"
mkfs.xfs -q -f -m reflink=1 "${work}/xfs.img"
mount -o loop "${work}/xfs.img" "${xfs}"

step "Go binaries"
(
  cd "${here}"
  export CGO_ENABLED=0 GOOS=linux GOARCH=amd64
  go build -buildvcs=false -trimpath -o "${work}/bin/host-agent" ./cmd/host-agent
  go build -buildvcs=false -trimpath -o "${work}/bin/guest-daemon" ./cmd/guest-daemon
  go build -buildvcs=false -trimpath -o "${work}/bin/egress-relay" ./cmd/egress-relay
  go test -c -buildvcs=false -tags kvm -o "${work}/bin/hostagent-kvm.test" ./internal/kvmtest
)

# Images the tests run, pulled through the cache and tagged with the names
# the tests use.
step "images"
pull_as() {
  docker pull -q "${registry}/$1" >/dev/null
  [ "${registry}/$1" = "$2" ] || docker tag "${registry}/$1" "$2"
}
pull_as "${source_image}" "${source_image}"
mkdir -p "${work}/agent-image"
cat >"${work}/agent-image/Dockerfile" <<EOF
FROM ${registry}/library/debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends e2fsprogs util-linux xfsprogs ca-certificates \
 && rm -rf /var/lib/apt/lists/*
EOF
docker build -q -t craft-fc-kvm-agent:local "${work}/agent-image" >/dev/null

# The kit root drive: the source image with fc-init and the prototype guest
# agent (fc-agent.py, vsock port 52).
step "kit root drive"
img="${work}/img"
tree="${work}/kit-tree"
mkdir -p "${img}" "${tree}"
cid=$(docker create "${source_image}")
docker export "${cid}" | tar -C "${tree}" -xf -
docker rm "${cid}" >/dev/null
install -m 0755 "${testdata}/kit/fc-init" "${tree}/sbin/fc-init"
install -m 0644 "${testdata}/kit/fc-agent.py" "${tree}/opt/fc-agent.py"
mkdir -p "${tree}/mnt/scratch"
size=$(($(du -sm "${tree}" | cut -f1) + 1024))
truncate -s "${size}M" "${img}/rootfs.ext4"
mkfs.ext4 -q -F -d "${tree}" -L root "${img}/rootfs.ext4"
rm -rf "${tree}"
cp "${artifacts}/vmlinux" "${img}/vmlinux"
truncate -s 1G "${img}/scratch-empty.ext4"
mkfs.ext4 -q -F -L scratch "${img}/scratch-empty.ext4"

export KVM_ARTIFACTS_DIR="${artifacts}" KVM_IMG_DIR="${img}" KVM_VMS="${vms}" \
  KVM_LOG_DIR="${work}/logs" KVM_AGENT_BIN="${work}/bin/host-agent" KVM_AGENT_IMAGE=craft-fc-kvm-agent:local \
  KVM_PR_BACKEND="${repo}/backend" KVM_HARNESS_DIR="${testdata}/harness"

if [ "${lane}" = full ]; then
  pull_as library/redis:7-alpine redis:7-alpine
  (cd "${repo}/backend" && SANDBOX_RUNTIME=firecracker CACHE_BACKEND=redis MULTI_TENANT=false "${KVM_PYTHON}" -c \
    'import onyx.sandbox_proxy.addons.gate, onyx.server.features.microvm.api, onyx.microvm.registry')

  # The pass-through proxy CA. mitmproxy writes it at its first start.
  step "proxy CA"
  confdir="${work}/proxy-confdir"
  mkdir -p "${confdir}"
  "$(dirname "${KVM_PYTHON}")/mitmdump" --set confdir="${confdir}" -p 18099 >/dev/null 2>&1 &
  mitm=$!
  for _ in $(seq 1 300); do
    [ -s "${confdir}/mitmproxy-ca-cert.pem" ] && break
    sleep 0.1
  done
  kill "${mitm}" 2>/dev/null || true
  wait "${mitm}" 2>/dev/null || true
  mitm=""
  [ -s "${confdir}/mitmproxy-ca-cert.pem" ] || {
    echo "mitmproxy wrote no CA" >&2
    exit 1
  }

  # Root drives from build-rootfs.sh: "ca" with the proxy CA built in
  # (pass-through, template and managed drive tests), "reclaim" with the
  # memory test daemon command, "noca" for the delivery image. "ca" and
  # "reclaim" run commands as root (--command-user=): the managed drive and
  # memory tests remount, drop caches and read /dev/vda. "noca" keeps the
  # production default, commands as the sandbox user.
  pull_registry=()
  [ -z "${BASE_IMAGE_REGISTRY:-}" ] || pull_registry=(--registry "${BASE_IMAGE_REGISTRY}")
  rootfs() {
    step "root drive $1"
    bash "${repo}/deployment/craft-fc/rootfs/build-rootfs.sh" --image "${source_image}" "${pull_registry[@]}" \
      --daemon-bin "${work}/bin/guest-daemon" --relay-bin "${work}/bin/egress-relay" \
      --out "${work}/rootfs-$1" "${@:2}" | tail -3
  }
  ca="${confdir}/mitmproxy-ca-cert.pem"
  rootfs ca --ca "${ca}" --daemon-cmd "/craft-fc/bin/guest-daemon --command-user="
  rootfs reclaim --ca "${ca}" --daemon-cmd "/craft-fc/bin/guest-daemon --reclaim-idle=1m --command-user="
  rootfs noca
  pt_img="${work}/img-pt"
  mkdir -p "${pt_img}"
  cp --sparse=always "${work}/rootfs-ca/rootfs.ext4" "${pt_img}/rootfs.ext4"
  cp "${artifacts}/vmlinux" "${pt_img}/vmlinux"
  cp "${img}/scratch-empty.ext4" "${pt_img}/scratch-empty.ext4"
  bash "${repo}/deployment/craft-fc/rootfs/check-image.sh" --context-from "${work}/rootfs-noca" "${work}/rd-context"
  docker build -q -t craft-fc-rootfs:kvm -f "${work}/rd-context/Dockerfile.image" "${work}/rd-context" >/dev/null
  export KVM_PROXY_CONFDIR="${confdir}" KVM_TB_CA="${ca}" KVM_RD_IMAGE=craft-fc-rootfs:kvm KVM_RD_DIR="${work}/rd"
fi

failed=""
for test in ${tests}; do
  extra=()
  case "${test}" in
    TestPassthroughKVM | TestSavesKVM) extra=("KVM_IMG_DIR=${pt_img}" "KVM_CERT_DIR=${work}/certs-pt") ;;
    TestTemplateBuildKVM) extra=("KVM_TB_ROOTFS=${work}/rootfs-ca" "KVM_CERT_DIR=${work}/certs-tb") ;;
    TestManagedSwapKVM) extra=("KVM_TB_ROOTFS=${work}/rootfs-ca" "KVM_CERT_DIR=${work}/certs-ms") ;;
    TestMemAdmissionKVM | TestMemOOMKVM) extra=("KVM_TB_ROOTFS=${work}/rootfs-reclaim" "KVM_CERT_DIR=${work}/certs-ma") ;;
  esac
  step "${test}"
  # Each test gets an empty data dir: no journal or templates of another test.
  data="${xfs}/${test}"
  mkdir -p "${data}"
  t0=$(date +%s)
  rc=0
  # A process group of its own: a Go test timeout does not run t.Cleanup, so
  # the group kill also stops the test's host services (the proxy harness).
  setsid env "KVM_DATA_DIR=${data}" "${extra[@]}" "${work}/bin/hostagent-kvm.test" -test.v -test.timeout=45m \
    -test.run "^${test}\$" &
  test_pid=$!
  wait "${test_pid}" || rc=$?
  kill -KILL -- "-${test_pid}" 2>/dev/null || true
  test_pid=""
  echo "RESULT ${test} rc=${rc} seconds=$(($(date +%s) - t0))"
  cleanup_vms
  if [ "${rc}" -ne 0 ]; then
    failed="${failed} ${test}"
    show_logs "${data}"
    show_logs "${work}/logs"
  fi
  rm -rf --one-file-system "${data}"
done
if [ -n "${failed}" ]; then
  echo "FAILED:${failed}" >&2
  exit 1
fi
echo "PASS ${lane}"
