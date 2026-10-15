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
DEVMAPPER_DATA_SIZE="${DEVMAPPER_DATA_SIZE:-8G}"
DEVMAPPER_META_SIZE="${DEVMAPPER_META_SIZE:-1G}"
DEVMAPPER_BASE_IMAGE_SIZE="${DEVMAPPER_BASE_IMAGE_SIZE:-4GB}"

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
  local role_label
  assert_kind_node_for_cluster "${KIND_NODE_NAME}"
  role_label="$(docker inspect -f '{{ index .Config.Labels "io.x-k8s.kind.role" }}' "${KIND_NODE_NAME}")"
  if [ "${role_label}" != "control-plane" ]; then
    echo "::error::refusing to configure ${KIND_NODE_NAME}; expected control-plane, got role=${role_label}" >&2
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

for bin in dmsetup losetup blockdev containerd ctr systemctl awk sed truncate; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    echo "::error::${bin} is required inside the kind node" >&2
    exit 1
  fi
done
for dev in /dev/kvm /dev/vhost-vsock; do
  if [ ! -e "${dev}" ]; then
    echo "::error::${dev} is not mounted into the kind node" >&2
    exit 1
  fi
done

modprobe dm_thin_pool || true
modprobe loop || true

mkdir -p "${DEVMAPPER_DATA_DIR}"
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
truncate -s "${DEVMAPPER_DATA_SIZE}" "${data_file}"
truncate -s "${DEVMAPPER_META_SIZE}" "${meta_file}"

data_loop="$(losetup --find --show "${data_file}")"
meta_loop="$(losetup --find --show "${meta_file}")"
data_bytes="$(blockdev --getsize64 "${data_loop}")"
data_sectors="$((data_bytes / 512))"
dmsetup create "${DEVMAPPER_POOL_NAME}" \
  --table "0 ${data_sectors} thin-pool ${meta_loop} ${data_loop} 128 32768"

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

systemctl restart containerd
ctr plugins ls | awk '
  $1 ~ /snapshotter/ && $2 == "devmapper" && $4 == "ok" { found = 1 }
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

verify_runtime() {
  require_bin docker
  require_bin kubectl
  verify_pinned_firecracker

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
