#!/usr/bin/env bash
# Builds the Craft Firecracker images for a dev cluster and pushes them to a
# private ECR registry. A stopgap until the Docker Hub images (ENG-4536) and
# the rootfs delivery product exist. Run it from a clean checkout of the commit
# you want: the default tag is that commit.
#
# Usage:
#   push-dev-ecr.sh artifacts
#   push-dev-ecr.sh host-agent
#   push-dev-ecr.sh runtime
#   push-dev-ecr.sh rootfs --image REF --ca CA.pem --suffix NAME
#
#   artifacts   deployment/craft-fc/Dockerfile.artifacts (kernel, Firecracker,
#               jailer) -> onyxdotapp/craft-fc-artifacts:<tag>, and the kernel
#               source -> <tag>-source. Checked with check-artifacts.sh after
#               the push.
#   host-agent  microvm/Dockerfile on top of craft-fc-artifacts:<tag> from the
#               same registry -> onyxdotapp/craft-fc-host-agent:<tag>. Checked
#               with microvm/check-image.sh after the push.
#   runtime     deployment/craft-runtime (the rootfs source image of the new
#               harness) -> onyxdotapp/craft-runtime:<tag>. Needs a checkout
#               that has deployment/craft-runtime.
#   rootfs      build-rootfs.sh on --image (a source image in the registry),
#               with the guest daemon and egress relay of this checkout and the
#               deployment's egress CA (--ca, public certificate only) ->
#               onyxdotapp/craft-fc-rootfs:<tag>-<suffix>. The image copies the
#               files into the host agent data dir from an init container
#               (rootfs/install-rootfs.sh, see deployment/craft-fc/README.md).
#
# Environment:
#   ECR_REGISTRY  Default 855178474906.dkr.ecr.us-west-2.amazonaws.com
#   TAG           Default: the short (10) commit of this checkout
#
# Needs Docker with buildx (linux/amd64 builds, emulation on arm64 is fine) and
# the AWS CLI with push access to the registry. Creates missing repositories.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "${here}/../.." && pwd)"
registry="${ECR_REGISTRY:-855178474906.dkr.ecr.us-west-2.amazonaws.com}"
region="$(cut -d. -f4 <<<"${registry}")"
commit="$(git -C "${repo}" rev-parse HEAD)"
tag="${TAG:-$(git -C "${repo}" rev-parse --short=10 HEAD)}"
# Pinned like microvm/Dockerfile and the rootfs helper.
golang_image="docker.io/library/golang:1.27.1-alpine@sha256:8a5910f31396cd4d89662f56c68b3ae31d374308270a1c3bd96672ee5ed43414"
alpine_image="docker.io/library/alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"

log() { echo "== $(date -u +%T) $*"; }
die() {
  echo "$*" >&2
  exit 1
}

if [ -n "$(git -C "${repo}" status --porcelain --untracked-files=no)" ]; then
  [ -n "${ALLOW_DIRTY:-}" ] || die "the checkout has uncommitted changes; the tag would not match the content (set ALLOW_DIRTY=1 to override)"
fi

ecr_login() {
  aws ecr get-login-password --region "${region}" | docker login --username AWS --password-stdin "${registry}" >/dev/null
}

ensure_repo() {
  aws ecr describe-repositories --region "${region}" --repository-names "$1" >/dev/null 2>&1 ||
    aws ecr create-repository --region "${region}" --repository-name "$1" \
      --image-scanning-configuration scanOnPush=true >/dev/null
}

# Refuses to move a tag: a dev cluster pins the tag, so its content must not change.
refuse_existing() {
  if aws ecr describe-images --region "${region}" --repository-name "$1" --image-ids "imageTag=$2" >/dev/null 2>&1; then
    die "${registry}/$1:$2 already exists"
  fi
}

digest_of() {
  aws ecr describe-images --region "${region}" --repository-name "$1" --image-ids "imageTag=$2" \
    --query 'imageDetails[0].imageDigest' --output text
}

push_artifacts() {
  local name=onyxdotapp/craft-fc-artifacts ref
  ref="${registry}/${name}:${tag}"
  ensure_repo "${name}"
  refuse_existing "${name}" "${tag}-source"
  refuse_existing "${name}" "${tag}"
  # GPL-2.0: the kernel source goes first, so vmlinux never exists here without it.
  log "build and push ${ref}-source"
  docker buildx build --platform linux/amd64 -f "${here}/Dockerfile.artifacts" --target source \
    --build-arg "ONYX_COMMIT=${commit}" --provenance=false -t "${ref}-source" --push "${here}"
  log "build and push ${ref}"
  docker buildx build --platform linux/amd64 -f "${here}/Dockerfile.artifacts" --target artifacts \
    --build-arg "ONYX_COMMIT=${commit}" --provenance=false -t "${ref}" --push "${here}"
  log "check ${ref}"
  local dir cid
  dir="$(mktemp -d)"
  docker pull --quiet --platform linux/amd64 "${ref}" >/dev/null
  cid="$(docker create --platform linux/amd64 "${ref}" /none)"
  docker cp "${cid}:/craft-fc" "${dir}/craft-fc"
  docker rm "${cid}" >/dev/null
  bash "${here}/check-artifacts.sh" "${dir}"
  rm -rf "${dir}"
  echo "${ref}@$(digest_of "${name}" "${tag}")"
}

push_host_agent() {
  local name=onyxdotapp/craft-fc-host-agent ref artifacts
  ref="${registry}/${name}:${tag}"
  artifacts="${registry}/onyxdotapp/craft-fc-artifacts:${tag}"
  aws ecr describe-images --region "${region}" --repository-name onyxdotapp/craft-fc-artifacts \
    --image-ids "imageTag=${tag}" >/dev/null 2>&1 || die "${artifacts} does not exist; run: $0 artifacts"
  ensure_repo "${name}"
  refuse_existing "${name}" "${tag}"
  log "build and push ${ref} (artifacts ${artifacts})"
  docker buildx build --platform linux/amd64 --build-arg "ARTIFACTS_IMAGE=${artifacts}" \
    --build-arg "VERSION=${tag}" --provenance=false -t "${ref}" --push "${repo}/microvm"
  log "check ${ref}"
  docker pull --quiet --platform linux/amd64 "${ref}" >/dev/null
  bash "${repo}/microvm/check-image.sh" "${ref}"
  echo "${ref}@$(digest_of "${name}" "${tag}")"
}

push_runtime() {
  local name=onyxdotapp/craft-runtime ref bake="${repo}/deployment/craft-runtime/docker-bake.hcl"
  [ -f "${bake}" ] || die "${bake} does not exist in this checkout"
  ref="${registry}/${name}:${tag}"
  ensure_repo "${name}"
  refuse_existing "${name}" "${tag}"
  log "build and push ${ref}"
  (cd "${repo}" && BUILDX_NO_DEFAULT_ATTESTATIONS=1 REGISTRY_IMAGE="${registry}/${name}" TAG="${tag}" IMAGE_VERSION="${tag}" \
    docker buildx bake -f "${bake}" --push runtime)
  echo "${ref}@$(digest_of "${name}" "${tag}")"
}

push_rootfs() {
  local image="" ca="" suffix=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --image) image=$2 ;;
      --ca) ca=$2 ;;
      --suffix) suffix=$2 ;;
      *) die "unknown argument: $1" ;;
    esac
    shift 2
  done
  [ -n "${image}" ] && [ -n "${ca}" ] && [ -n "${suffix}" ] ||
    die "usage: $0 rootfs --image REF --ca CA.pem --suffix NAME"
  [[ "${suffix}" =~ ^[a-z0-9][a-z0-9.-]*$ ]] || die "--suffix: lower-case letters, digits, '.' and '-' only"
  grep -q 'PRIVATE KEY' "${ca}" && die "${ca} has a private key. Pass the public CA certificate only."

  local name=onyxdotapp/craft-fc-rootfs ref work
  ref="${registry}/${name}:${tag}-${suffix}"
  ensure_repo "${name}"
  refuse_existing "${name}" "${tag}-${suffix}"
  work="$(mktemp -d)"
  # shellcheck disable=SC2064 # expand now: work is local.
  trap "rm -rf '${work}'" EXIT
  mkdir -p "${work}/bin" "${work}/out" "${work}/docker"
  cp "${ca}" "${work}/egress-ca.crt"

  log "build guest-daemon and egress-relay (${commit})"
  docker run --rm -v "${repo}/microvm:/src:ro" -v "${work}/bin:/out" -w /src \
    -e GOOS=linux -e GOARCH=amd64 -e CGO_ENABLED=0 -e GOFLAGS=-buildvcs=false "${golang_image}" \
    sh -euc 'go build -trimpath -o /out/guest-daemon ./cmd/guest-daemon && go build -trimpath -o /out/egress-relay ./cmd/egress-relay'

  # build-rootfs.sh needs Linux and root. Run it in an amd64 helper container
  # that talks to this Docker daemon. The registry login goes in a temporary
  # Docker config (no credential helper in the container).
  # Pin the linux/amd64 manifest. On a non-amd64 Docker host with the containerd
  # image store, `docker image inspect` of an index shows the host platform,
  # whose Env build-rootfs.sh would read as empty.
  local repo_part amd64
  repo_part="${image%@*}"
  case "${repo_part##*/}" in *:*) repo_part="${repo_part%:*}" ;; esac
  amd64="$(docker buildx imagetools inspect "${image}" \
    --format '{{range .Manifest.Manifests}}{{if and (eq .Platform.OS "linux") (eq .Platform.Architecture "amd64")}}{{.Digest}}{{end}}{{end}}')"
  [ -n "${amd64}" ] && image="${repo_part}@${amd64}"
  log "build rootfs from ${image}"
  local auth common
  auth="$(printf 'AWS:%s' "$(aws ecr get-login-password --region "${region}")" | base64 | tr -d '\n')"
  (umask 077 && printf '{"auths":{"%s":{"auth":"%s"}}}\n' "${registry}" "${auth}" >"${work}/docker/config.json")
  # Mount the git dirs at the same paths, so the manifest records the commit
  # (a worktree's .git file points at the common dir).
  common="$(cd "${repo}" && cd "$(git rev-parse --git-common-dir)" && pwd)"
  docker run --rm --platform linux/amd64 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${repo}:${repo}:ro" -v "${common}:${common}:ro" -v "${work}:/work" \
    -e DOCKER_CONFIG=/work/docker "${alpine_image}" \
    sh -euc "apk add --no-cache -q bash docker-cli tar e2fsprogs e2fsprogs-extra python3 openssl coreutils file git grep util-linux findutils >/dev/null
      git config --global --add safe.directory '*'
      bash '${here}/rootfs/build-rootfs.sh' --image '${image}' --ca /work/egress-ca.crt \
        --daemon-bin /work/bin/guest-daemon --relay-bin /work/bin/egress-relay --out /work/out"
  rm -f "${work}/docker/config.json"

  log "package ${ref}"
  local ctx="${work}/image"
  mkdir -p "${ctx}"
  mv "${work}/out/rootfs.ext4" "${work}/out/manifest.json" "${ctx}/"
  cp "${work}/egress-ca.crt" "${ctx}/egress-ca.crt"
  (cd "${ctx}" && sha256sum rootfs.ext4 >rootfs.ext4.sha256)
  cp "${here}/rootfs/install-rootfs.sh" "${here}/rootfs/Dockerfile.image" "${ctx}/"
  docker buildx build --platform linux/amd64 -f "${ctx}/Dockerfile.image" --provenance=false \
    -t "${ref}" --push "${ctx}"
  log "manifest.json sha256: $(sha256sum "${ctx}/manifest.json" | cut -d' ' -f1)"
  echo "${ref}@$(digest_of "${name}" "${tag}-${suffix}")"
}

cmd="${1:-}"
[ $# -gt 0 ] && shift
ecr_login
case "${cmd}" in
  artifacts) push_artifacts ;;
  host-agent) push_host_agent ;;
  runtime) push_runtime ;;
  rootfs) push_rootfs "$@" ;;
  *) die "usage: $0 artifacts | host-agent | runtime | rootfs --image REF --ca CA.pem --suffix NAME" ;;
esac
