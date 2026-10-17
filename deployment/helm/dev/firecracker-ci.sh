#!/usr/bin/env bash
set -euo pipefail

KATA_DEPLOY_VERSION="${KATA_DEPLOY_VERSION:-4.2.0}"
KATA_DEPLOY_SHA256="${KATA_DEPLOY_SHA256:-52a3e9139e810d58867a7676fb38957870dd09e8b2033e54cebdda7c97598e8c}"
KATA_DEPLOY_URL="${KATA_DEPLOY_URL:-https://github.com/kata-containers/kata-containers/releases/download/${KATA_DEPLOY_VERSION}/kata-deploy-${KATA_DEPLOY_VERSION}.tgz}"
KATA_NAMESPACE="${KATA_NAMESPACE:-kata-system}"
KATA_SMOKE_NAMESPACE="${KATA_SMOKE_NAMESPACE:-kata-firecracker-smoke}"
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-onyx-craft-ci}"
KIND_NODE_NAME="${KIND_NODE_NAME:-onyx-craft-ci-control-plane}"
KATA_INSTALL_NODE_NAMES="${KATA_INSTALL_NODE_NAMES:-${KIND_NODE_NAME}}"
KATA_SMOKE_IMAGE="${KATA_SMOKE_IMAGE:-${SANDBOX_CONTAINER_IMAGE:-localhost:5001/onyx-sandbox:ci}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
FIRECRACKER_PIN_HELPER="${FIRECRACKER_PIN_HELPER:-${REPO_ROOT}/deployment/firecracker/install-pinned-firecracker.sh}"

DEVMAPPER_POOL_NAME="${DEVMAPPER_POOL_NAME:-kata_ci_devpool}"
DEVMAPPER_DATA_DIR="${DEVMAPPER_DATA_DIR:-/var/lib/containerd/devmapper-kata-ci}"
DEVMAPPER_DATA_SIZE="${DEVMAPPER_DATA_SIZE:-16G}"
DEVMAPPER_META_SIZE="${DEVMAPPER_META_SIZE:-1G}"
DEVMAPPER_BASE_IMAGE_SIZE="${DEVMAPPER_BASE_IMAGE_SIZE:-8GB}"

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "::error::$1 is required" >&2
    exit 1
  fi
}

trim_space() {
  local value
  value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  echo "${value}"
}

assert_kind_node_for_cluster() {
  local node cluster_label
  node="$1"

  if ! docker inspect "${node}" >/dev/null 2>&1; then
    echo "::error::kind node container ${node} does not exist" >&2
    exit 1
  fi
  cluster_label="$(docker inspect -f '{{ index .Config.Labels "io.x-k8s.kind.cluster" }}' "${node}")"
  if [ "${cluster_label}" != "${KIND_CLUSTER_NAME}" ]; then
    echo "::error::refusing to configure ${node}; expected kind cluster ${KIND_CLUSTER_NAME}, got cluster=${cluster_label}" >&2
    exit 1
  fi
}

preflight_host() {
  require_bin docker
  require_bin sudo
  require_bin findmnt

  if [ "$(uname -s)" != "Linux" ]; then
    echo "::error::Kata Firecracker CI requires a Linux runner" >&2
    exit 1
  fi
  if [ "$(uname -m)" != "x86_64" ]; then
    echo "::error::Kata Firecracker CI currently requires linux/amd64" >&2
    exit 1
  fi
  if ! grep -Eq '(vmx|svm)' /proc/cpuinfo; then
    echo "::error::runner CPU does not expose vmx/svm; RunsOn nested-virt is required" >&2
    exit 1
  fi
  if [ "$(findmnt --noheadings --output FSTYPE --target /dev)" != devtmpfs ]; then
    echo "::error::host /dev must use devtmpfs for dynamic devmapper devices" >&2
    exit 1
  fi

  sudo -n true
  sudo -n modprobe kvm || true
  if grep -Eq 'vmx' /proc/cpuinfo; then
    sudo -n modprobe kvm_intel || true
  fi
  if grep -Eq 'svm' /proc/cpuinfo; then
    sudo -n modprobe kvm_amd || true
  fi
  sudo -n modprobe vhost_vsock || true
  sudo -n modprobe dm_thin_pool || true
  sudo -n modprobe loop || true

  if [ ! -c /dev/kvm ] || [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
    echo "::error::/dev/kvm is not readable and writable on the runner" >&2
    exit 1
  fi
  if [ ! -e /dev/vhost-vsock ]; then
    echo "::error::/dev/vhost-vsock is missing; Firecracker vsock support is required" >&2
    exit 1
  fi
  if [ ! -d /lib/modules ]; then
    echo "::error::/lib/modules is required so kata-deploy can load host modules" >&2
    exit 1
  fi
}

configure_kind_node() {
  require_bin docker
  require_bin findmnt
  local role_label dev_bind
  assert_kind_node_for_cluster "${KIND_NODE_NAME}"
  role_label="$(docker inspect -f '{{ index .Config.Labels "io.x-k8s.kind.role" }}' "${KIND_NODE_NAME}")"
  if [ "${role_label}" != "control-plane" ]; then
    echo "::error::refusing to configure ${KIND_NODE_NAME}; expected control-plane, got role=${role_label}" >&2
    exit 1
  fi
  dev_bind="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/dev"}}{{.Type}} {{.Source}} {{.RW}} {{.Propagation}}{{end}}{{end}}' "${KIND_NODE_NAME}")"
  if [ "${dev_bind}" != 'bind /dev true rprivate' ]; then
    echo "::error::kind node requires a writable /dev bind from host /dev with rprivate propagation" >&2
    exit 1
  fi
  if [ "$(findmnt --noheadings --output FSTYPE --target /dev)" != devtmpfs ]; then
    echo "::error::host /dev must use devtmpfs for dynamic devmapper devices" >&2
    exit 1
  fi

  docker exec -i \
    -e DEVMAPPER_POOL_NAME="${DEVMAPPER_POOL_NAME}" \
    -e DEVMAPPER_DATA_DIR="${DEVMAPPER_DATA_DIR}" \
    -e DEVMAPPER_DATA_SIZE="${DEVMAPPER_DATA_SIZE}" \
    -e DEVMAPPER_META_SIZE="${DEVMAPPER_META_SIZE}" \
    -e DEVMAPPER_BASE_IMAGE_SIZE="${DEVMAPPER_BASE_IMAGE_SIZE}" \
    "${KIND_NODE_NAME}" bash -s <<'NODE'
set -euo pipefail

export DM_DISABLE_UDEV=1

CONTAINERD_VERSION="v2.1.1"
CONTAINERD_REVISION="cb1076646aa3740577fafbf3d914198b7fe8e3f7"
CONTAINERD_X86_64_TGZ_SHA256="918e88fd393c28c89424e6535df0546ca36c1dfa7d8a5d685dee70b449380a9b"
CONTAINERD_URL="https://github.com/containerd/containerd/releases/download/${CONTAINERD_VERSION}/containerd-${CONTAINERD_VERSION#v}-linux-amd64.tar.gz"

for bin in dmsetup losetup blockdev containerd ctr systemctl awk sed truncate curl sha256sum tar install mktemp mv rm findmnt; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    echo "::error::${bin} is required inside the kind node" >&2
    exit 1
  fi
done
if [ "$(findmnt --noheadings --output FSTYPE --target /dev)" != devtmpfs ]; then
  echo "::error::node /dev must use devtmpfs for dynamic devmapper devices" >&2
  exit 1
fi
for dev in /dev/kvm /dev/vhost-vsock; do
  if [ ! -e "${dev}" ]; then
    echo "::error::${dev} is not mounted into the kind node" >&2
    exit 1
  fi
done

expected_version="containerd github.com/containerd/containerd/v2 ${CONTAINERD_VERSION} ${CONTAINERD_REVISION}"
installed_version="$(/usr/local/bin/containerd --version)"
if [ "${installed_version}" != "${expected_version}" ]; then
  echo "::error::installed containerd reported '${installed_version}', expected '${expected_version}'" >&2
  exit 1
fi

modprobe dm_thin_pool || true
modprobe loop || true

data_file="${DEVMAPPER_DATA_DIR}/data"
meta_file="${DEVMAPPER_DATA_DIR}/metadata"
if dmsetup info "${DEVMAPPER_POOL_NAME}" >/dev/null 2>&1; then
  echo "::error::devmapper pool ${DEVMAPPER_POOL_NAME} already exists; refusing to replace it" >&2
  exit 1
fi
if [ -e "${data_file}" ] || [ -e "${meta_file}" ]; then
  echo "::error::devmapper backing files already exist in ${DEVMAPPER_DATA_DIR}; refusing to truncate them" >&2
  exit 1
fi

containerd_staging="$(mktemp -d /usr/local/bin/.onyx-containerd.XXXXXX)"
trap 'rm -rf "${containerd_staging}"' EXIT
containerd_archive="${containerd_staging}/containerd.tar.gz"
curl --fail --location --silent --show-error \
  --retry 5 --retry-delay 2 --retry-all-errors \
  --output "${containerd_archive}" "${CONTAINERD_URL}"
echo "${CONTAINERD_X86_64_TGZ_SHA256}  ${containerd_archive}" | sha256sum --check -
tar -xzf "${containerd_archive}" --no-same-owner --no-same-permissions \
  -C "${containerd_staging}" bin/containerd
staged_containerd="${containerd_staging}/bin/containerd"
if [ ! -f "${staged_containerd}" ] || [ ! -x "${staged_containerd}" ] || [ -L "${staged_containerd}" ]; then
  echo "::error::verified archive must contain a regular executable bin/containerd" >&2
  exit 1
fi
staged_version="$("${staged_containerd}" --version)"
if [ "${staged_version}" != "${expected_version}" ]; then
  echo "::error::staged containerd reported '${staged_version}', expected '${expected_version}'" >&2
  exit 1
fi
install -m 0755 "${staged_containerd}" "${containerd_staging}/containerd"
mv "${containerd_staging}/containerd" /usr/local/bin/containerd

mkdir -p "${DEVMAPPER_DATA_DIR}"
truncate -s "${DEVMAPPER_DATA_SIZE}" "${data_file}"
truncate -s "${DEVMAPPER_META_SIZE}" "${meta_file}"

data_loop="$(losetup --find --show "${data_file}")"
meta_loop="$(losetup --find --show "${meta_file}")"
data_bytes="$(blockdev --getsize64 "${data_loop}")"
data_sectors="$((data_bytes / 512))"
dmsetup create "${DEVMAPPER_POOL_NAME}" \
  --table "0 ${data_sectors} thin-pool ${meta_loop} ${data_loop} 128 32768"

pool_path="/dev/mapper/${DEVMAPPER_POOL_NAME}"
dmsetup info "${DEVMAPPER_POOL_NAME}"
if [ ! -b "${pool_path}" ]; then
  echo "::error::devmapper pool ${pool_path} is not a block device" >&2
  dmsetup info "${pool_path}" >&2 || true
  exit 1
fi
dmsetup info "${pool_path}"
echo "Verified devmapper block device ${pool_path}"
dmsetup table "${DEVMAPPER_POOL_NAME}"
dmsetup status "${DEVMAPPER_POOL_NAME}"
dmsetup deps "${DEVMAPPER_POOL_NAME}"

config_version="$(containerd config dump | awk '$1 == "version" { print $3; exit }' || true)"
if [ -z "${config_version}" ]; then
  config_version="2"
fi
if [ "${config_version}" -ge 2 ]; then
  devmapper_plugin='io.containerd.snapshotter.v1.devmapper'
else
  devmapper_plugin='devmapper'
fi

config=/etc/containerd/config.toml
tmp="$(mktemp)"
sed '/^# BEGIN ONYX KATA FIRECRACKER CI DEVMAPPER$/,/^# END ONYX KATA FIRECRACKER CI DEVMAPPER$/d' \
  "${config}" > "${tmp}"
mv "${tmp}" "${config}"
{
  echo
  echo '# BEGIN ONYX KATA FIRECRACKER CI DEVMAPPER'
  echo "[plugins.\"${devmapper_plugin}\"]"
  echo "  pool_name = \"${DEVMAPPER_POOL_NAME}\""
  echo "  root_path = \"${DEVMAPPER_DATA_DIR}\""
  echo "  base_image_size = \"${DEVMAPPER_BASE_IMAGE_SIZE}\""
  echo "  discard_blocks = true"
  echo '# END ONYX KATA FIRECRACKER CI DEVMAPPER'
} >> "${config}"

mkdir -p /etc/systemd/system/containerd.service.d
printf '[Service]\nEnvironment=DM_DISABLE_UDEV=1\n' \
  > /etc/systemd/system/containerd.service.d/20-onyx-devmapper.conf
systemctl daemon-reload
systemctl restart containerd
ctr plugins ls | awk '
  $1 ~ /snapshotter/ && $2 == "devmapper" { print; if ($4 == "ok") found = 1 }
  END { exit !found }
'
NODE
}

run_firecracker_pin_helper_in_node() {
  require_bin docker

  local node command
  node="$1"
  command="$2"

  assert_kind_node_for_cluster "${node}"
  if [ ! -f "${FIRECRACKER_PIN_HELPER}" ]; then
    echo "::error::Firecracker pin helper not found at ${FIRECRACKER_PIN_HELPER}" >&2
    exit 1
  fi

  docker exec -i "${node}" bash -s -- "${command}" < "${FIRECRACKER_PIN_HELPER}"
}

install_pinned_firecracker() {
  local node
  IFS=',' read -r -a nodes <<< "${KATA_INSTALL_NODE_NAMES}"
  for node in "${nodes[@]}"; do
    node="$(trim_space "${node}")"
    [ -n "${node}" ] && run_firecracker_pin_helper_in_node "${node}" install
  done
}

verify_pinned_firecracker() {
  local node
  IFS=',' read -r -a nodes <<< "${KATA_INSTALL_NODE_NAMES}"
  for node in "${nodes[@]}"; do
    node="$(trim_space "${node}")"
    [ -n "${node}" ] && run_firecracker_pin_helper_in_node "${node}" verify
  done
}

install_kata() {
  require_bin curl
  require_bin helm
  require_bin kubectl
  require_bin sha256sum

  local tmp_dir chart values
  tmp_dir="$(mktemp -d)"
  chart="${tmp_dir}/kata-deploy-${KATA_DEPLOY_VERSION}.tgz"
  values="${tmp_dir}/kata-firecracker-values.yaml"

  curl --fail --location --silent --show-error \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --output "${chart}" "${KATA_DEPLOY_URL}"
  echo "${KATA_DEPLOY_SHA256}  ${chart}" | sha256sum --check -

  {
    echo "deploymentMode: job"
    echo "k8sDistribution: k8s"
    echo "job:"
    echo "  nodes:"
    IFS=',' read -r -a nodes <<< "${KATA_INSTALL_NODE_NAMES}"
    for node in "${nodes[@]}"; do
      node="$(trim_space "${node}")"
      [ -n "${node}" ] && echo "    - ${node}"
    done
    echo "  waitForNodesSeconds: 120"
    echo "  nodeSettleSeconds: 1"
    echo "  waitNodeReadySeconds: 180"
    echo "  ttlSecondsAfterFinished: 1200"
    echo "snapshotter:"
    echo "  setup: []"
    echo "shims:"
    echo "  disableAll: true"
    echo "  fc:"
    echo "    enabled: true"
    echo "    containerd:"
    echo "      snapshotter: devmapper"
    echo "defaultShim:"
    echo "  amd64: fc"
    echo "runtimeClasses:"
    echo "  enabled: true"
    echo "  createDefault: false"
    echo "node-feature-discovery:"
    echo "  enabled: false"
  } > "${values}"

  helm upgrade --install kata-deploy "${chart}" \
    --namespace "${KATA_NAMESPACE}" \
    --create-namespace \
    --values "${values}" \
    --wait \
    --timeout 15m

  kubectl get runtimeclass kata-fc >/dev/null
  kubectl get runtimeclass kata-fc -o jsonpath='{.handler}' | grep -qx 'kata-fc'
  kubectl get node "${KIND_NODE_NAME}" \
    -o jsonpath='{.metadata.labels.katacontainers\.io/kata-runtime}' | grep -qx 'true'
  install_pinned_firecracker
}

verify_devmapper_snapshot() (
  require_bin docker
  require_bin findmnt
  require_bin stat
  require_bin sudo
  require_bin blockdev
  assert_kind_node_for_cluster "${KIND_NODE_NAME}"
  if [ "$(findmnt --noheadings --output FSTYPE --target /dev)" != devtmpfs ] || \
    [ "$(docker exec "${KIND_NODE_NAME}" findmnt --noheadings --output FSTYPE --target /dev)" != devtmpfs ]; then
    echo "::error::host and node /dev must use devtmpfs for dynamic devmapper devices" >&2
    exit 1
  fi
  docker exec "${KIND_NODE_NAME}" bash -c 'for bin in ctr jq stat blockdev awk; do command -v "${bin}" >/dev/null || exit 1; done'
  docker exec "${KIND_NODE_NAME}" ctr plugins ls | awk '
    $1 ~ /snapshotter/ && $2 == "devmapper" { print; if ($4 == "ok") found = 1 }
    END { exit !found }
  '

  snapshot_cli=(docker exec "${KIND_NODE_NAME}" ctr --namespace k8s.io snapshots --snapshotter devmapper)
  probe_key="onyx-devmapper-probe-$(cat /proc/sys/kernel/random/uuid)"
  snapshot_keys="$("${snapshot_cli[@]}" list)"
  if printf '%s\n' "${snapshot_keys}" | awk -v key="${probe_key}" 'NR > 1 && $1 == key { found = 1 } END { exit !found }'; then
    echo "::error::devmapper probe ${probe_key} already exists; refusing to replace it" >&2
    exit 1
  fi
  created=false
  status=0
  trap 'status=$?; if [ "${created}" = true ]; then if ! "${snapshot_cli[@]}" remove "${probe_key}"; then echo "::error::failed to remove owned devmapper probe ${probe_key}" >&2; status=1; fi; fi; exit "${status}"' EXIT
  mounts="$("${snapshot_cli[@]}" prepare --mounts "${probe_key}")"
  created=true
  snapshot_source="$(printf '%s\n' "${mounts}" | docker exec -i "${KIND_NODE_NAME}" jq -er \
    'if type == "array" and length == 1 then .[0].Source | select(type == "string") else error("expected one snapshot mount") end')"
  if [[ "${snapshot_source}" != "/dev/mapper/${DEVMAPPER_POOL_NAME}-snap-"* ]] || \
    [[ ! "${snapshot_source##*-snap-}" =~ ^[0-9]+$ ]]; then
    echo "::error::unexpected devmapper snapshot source ${snapshot_source}" >&2
    exit 1
  fi
  if ! docker exec "${KIND_NODE_NAME}" test -b "${snapshot_source}"; then
    echo "::error::devmapper snapshot source ${snapshot_source} is not a block device" >&2
    exit 1
  fi
  rdev="$(docker exec "${KIND_NODE_NAME}" stat -Lc '%t:%T' "${snapshot_source}")"
  if [[ ! "${rdev}" =~ ^[[:xdigit:]]+:[[:xdigit:]]+$ ]]; then
    echo "::error::invalid devmapper device identity ${rdev}" >&2
    exit 1
  fi
  sysfs_path="/sys/dev/block/$((16#${rdev%:*})):$((16#${rdev#*:}))/uevent"
  devname="$(docker exec "${KIND_NODE_NAME}" awk -F= '$1 == "DEVNAME" { print $2 }' "${sysfs_path}")"
  if [[ ! "${devname}" =~ ^dm-[0-9]+$ ]] || \
    [ "$(awk -F= '$1 == "DEVNAME" { print $2 }' "${sysfs_path}")" != "${devname}" ]; then
    echo "::error::host and node sysfs disagree on devmapper device identity" >&2
    exit 1
  fi
  canonical_path="/dev/${devname}"
  if [ ! -b "${canonical_path}" ] || ! docker exec "${KIND_NODE_NAME}" test -b "${canonical_path}"; then
    echo "::error::canonical devmapper device ${canonical_path} is missing or is not a block device on host or node" >&2
    exit 1
  fi
  if [ "$(stat -Lc '%t:%T' "${canonical_path}")" != "${rdev}" ] || \
    [ "$(docker exec "${KIND_NODE_NAME}" stat -Lc '%t:%T' "${canonical_path}")" != "${rdev}" ]; then
    echo "::error::host and node canonical devmapper device identity does not match ${rdev}" >&2
    exit 1
  fi
  node_bytes="$(docker exec "${KIND_NODE_NAME}" blockdev --getsize64 "${canonical_path}")"
  host_bytes="$(sudo -n blockdev --getsize64 "${canonical_path}")"
  if [[ ! "${node_bytes}" =~ ^[0-9]+$ ]] || [ "${node_bytes}" -eq 0 ] || [ "${host_bytes}" != "${node_bytes}" ]; then
    echo "::error::host and node canonical devmapper device size must be positive and match" >&2
    exit 1
  fi
  printf 'Verified devmapper probe %s source=%s canonical=%s rdev=%s bytes=%s\n' \
    "${probe_key}" "${snapshot_source}" "${canonical_path}" "${rdev}" "${node_bytes}"
)

verify_runtime() {
  require_bin docker
  require_bin kubectl
  verify_pinned_firecracker
  verify_devmapper_snapshot

  local smoke_name
  smoke_name="kata-fc-smoke"
  kubectl create namespace "${KATA_SMOKE_NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "${KATA_SMOKE_NAMESPACE}" delete pod "${smoke_name}" \
    --ignore-not-found --wait=true >/dev/null
  trap 'kubectl -n "${KATA_SMOKE_NAMESPACE:-kata-firecracker-smoke}" delete pod kata-fc-smoke --ignore-not-found --wait=false >/dev/null 2>&1 || true' EXIT

  kubectl -n "${KATA_SMOKE_NAMESPACE}" apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${smoke_name}
spec:
  restartPolicy: Never
  runtimeClassName: kata-fc
  containers:
    - name: smoke
      image: ${KATA_SMOKE_IMAGE}
      imagePullPolicy: IfNotPresent
      command: ["sh", "-c", "cat /proc/sys/kernel/random/boot_id; sleep 600"]
YAML

  if ! kubectl -n "${KATA_SMOKE_NAMESPACE}" wait --for=condition=Ready "pod/${smoke_name}" --timeout=240s; then
    kubectl -n "${KATA_SMOKE_NAMESPACE}" describe pod "${smoke_name}" || true
    kubectl -n "${KATA_SMOKE_NAMESPACE}" logs "${smoke_name}" --all-containers=true || true
    exit 1
  fi

  local pod_node node_boot_id guest_boot_id
  pod_node="$(kubectl -n "${KATA_SMOKE_NAMESPACE}" get pod "${smoke_name}" -o jsonpath='{.spec.nodeName}')"
  node_boot_id="$(kubectl get node "${pod_node}" -o jsonpath='{.status.nodeInfo.bootID}')"
  guest_boot_id="$(kubectl -n "${KATA_SMOKE_NAMESPACE}" exec "${smoke_name}" -- cat /proc/sys/kernel/random/boot_id)"
  printf 'Kata smoke boot IDs node=%s guest=%s\n' "${node_boot_id}" "${guest_boot_id}"

  if [ -z "${node_boot_id}" ] || [ -z "${guest_boot_id}" ]; then
    echo "::error::failed to read node or guest boot ID" >&2
    exit 1
  fi
  if [ "${node_boot_id}" = "${guest_boot_id}" ]; then
    echo "::error::Kata Firecracker smoke pod boot ID matches the Kubernetes node boot ID" >&2
    exit 1
  fi

  run_firecracker_pin_helper_in_node "${KIND_NODE_NAME}" verify-live-process
  kubectl -n "${KATA_SMOKE_NAMESPACE}" get pod "${smoke_name}" -o jsonpath='{.spec.runtimeClassName}' | grep -qx 'kata-fc'
  kubectl get runtimeclass kata-fc -o jsonpath='{.handler}' | grep -qx 'kata-fc'
}

case "${1:-}" in
  preflight-host|configure-kind-node|install-kata|verify|all)
    if [ "${ONYX_FIRECRACKER_DEDICATED_HOST:-false}" != true ]; then
      echo "::error::set ONYX_FIRECRACKER_DEDICATED_HOST=true only on a dedicated disposable Linux host or test VM; setup shares host /dev and device metadata" >&2
      exit 1
    fi
    ;;
esac

case "${1:-}" in
  preflight-host)
    preflight_host
    ;;
  configure-kind-node)
    configure_kind_node
    ;;
  install-kata)
    install_kata
    ;;
  verify)
    verify_runtime
    ;;
  all)
    preflight_host
    configure_kind_node
    install_kata
    verify_runtime
    ;;
  *)
    echo "usage: $0 {preflight-host|configure-kind-node|install-kata|verify|all}" >&2
    exit 2
    ;;
esac
