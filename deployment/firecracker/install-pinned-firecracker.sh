#!/usr/bin/env bash
set -euo pipefail

FIRECRACKER_VERSION="v1.17.0"
FIRECRACKER_X86_64_TGZ_SHA256="06094a1108ae9e82aa4c23a775aa92758f53f1175d422270d9d6162cb9ade558"
FIRECRACKER_AARCH64_TGZ_SHA256="e351ebe4f7a16b5873bbd51005d2e6767103cff4d5ebc829df2d3f95a93e2256"
FIRECRACKER_RELEASE_BASE_URL="https://github.com/firecracker-microvm/firecracker/releases/download/${FIRECRACKER_VERSION}"

INSTALL_ARCH="${ONYX_FIRECRACKER_ARCH:-$(uname -m)}"
INSTALL_DIR="${ONYX_FIRECRACKER_INSTALL_DIR:-/opt/kata/bin}"
FIRECRACKER_BIN="${INSTALL_DIR}/firecracker"
JAILER_BIN="${INSTALL_DIR}/jailer"

error() {
  echo "::error::$*" >&2
  exit 1
}

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    error "$1 is required"
  fi
}

archive_sha256() {
  case "${INSTALL_ARCH}" in
    x86_64)
      echo "${FIRECRACKER_X86_64_TGZ_SHA256}"
      ;;
    aarch64)
      echo "${FIRECRACKER_AARCH64_TGZ_SHA256}"
      ;;
    *)
      error "unsupported Firecracker architecture ${INSTALL_ARCH}; expected x86_64 or aarch64"
      ;;
  esac
}

archive_url() {
  echo "${ONYX_FIRECRACKER_ARCHIVE_URL:-${FIRECRACKER_RELEASE_BASE_URL}/firecracker-${FIRECRACKER_VERSION}-${INSTALL_ARCH}.tgz}"
}

archive_root() {
  echo "release-${FIRECRACKER_VERSION}-${INSTALL_ARCH}"
}

download_archive() {
  require_bin curl
  require_bin sha256sum

  local archive_path
  archive_path="$1"

  curl --fail --location --silent --show-error \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --output "${archive_path}" "$(archive_url)"
  echo "$(archive_sha256)  ${archive_path}" | sha256sum --check -
}

extract_archive() {
  require_bin tar

  local archive_path extract_dir root
  archive_path="$1"
  extract_dir="$2"
  root="$(archive_root)"

  tar --extract --gzip --file "${archive_path}" \
    --directory "${extract_dir}" \
    --no-same-owner \
    --no-same-permissions \
    "${root}/firecracker-${FIRECRACKER_VERSION}-${INSTALL_ARCH}" \
    "${root}/jailer-${FIRECRACKER_VERSION}-${INSTALL_ARCH}"
}

source_firecracker_path() {
  local extract_dir
  extract_dir="$1"
  echo "${extract_dir}/$(archive_root)/firecracker-${FIRECRACKER_VERSION}-${INSTALL_ARCH}"
}

source_jailer_path() {
  local extract_dir
  extract_dir="$1"
  echo "${extract_dir}/$(archive_root)/jailer-${FIRECRACKER_VERSION}-${INSTALL_ARCH}"
}

assert_version() {
  local binary expected_name expected_output output status first_line
  binary="$1"
  expected_name="$2"
  expected_output="$3"

  if [ ! -x "${binary}" ]; then
    error "${expected_name} is not executable at ${binary}"
  fi
  status=0
  output="$("${binary}" --version 2>&1)" || status=$?
  if [ "${status}" -ne 0 ]; then
    error "${expected_name} at ${binary} failed --version: ${output}"
  fi
  first_line="$(printf '%s\n' "${output}" | sed -n '1p')"
  if [ "${first_line}" != "${expected_output}" ]; then
    error "${expected_name} at ${binary} reported '${first_line}', expected '${expected_output}'"
  fi
}

assert_source_binaries() {
  local extract_dir firecracker_src jailer_src
  extract_dir="$1"
  firecracker_src="$(source_firecracker_path "${extract_dir}")"
  jailer_src="$(source_jailer_path "${extract_dir}")"

  assert_version "${firecracker_src}" "Firecracker archive binary" "Firecracker ${FIRECRACKER_VERSION}"
  assert_version "${jailer_src}" "Firecracker jailer archive binary" "Jailer ${FIRECRACKER_VERSION}"
}

install_binaries() {
  require_bin install

  local extract_dir firecracker_src jailer_src
  extract_dir="$1"
  firecracker_src="$(source_firecracker_path "${extract_dir}")"
  jailer_src="$(source_jailer_path "${extract_dir}")"

  if [ ! -d "${INSTALL_DIR}" ]; then
    error "Kata binary directory ${INSTALL_DIR} does not exist; install Kata before pinning Firecracker"
  fi
  install -m 0755 "${firecracker_src}" "${FIRECRACKER_BIN}"
  install -m 0755 "${jailer_src}" "${JAILER_BIN}"
}

assert_installed_checksums() {
  require_bin sha256sum

  local extract_dir expected_firecracker actual_firecracker expected_jailer actual_jailer
  extract_dir="$1"

  expected_firecracker="$(sha256sum "$(source_firecracker_path "${extract_dir}")" | awk '{ print $1 }')"
  actual_firecracker="$(sha256sum "${FIRECRACKER_BIN}" | awk '{ print $1 }')"
  expected_jailer="$(sha256sum "$(source_jailer_path "${extract_dir}")" | awk '{ print $1 }')"
  actual_jailer="$(sha256sum "${JAILER_BIN}" | awk '{ print $1 }')"

  if [ "${actual_firecracker}" != "${expected_firecracker}" ]; then
    error "${FIRECRACKER_BIN} checksum does not match the verified ${FIRECRACKER_VERSION} archive"
  fi
  if [ "${actual_jailer}" != "${expected_jailer}" ]; then
    error "${JAILER_BIN} checksum does not match the verified ${FIRECRACKER_VERSION} archive"
  fi
}

with_verified_archive() {
  local action
  action="$1"
  (
    local tmp_dir archive_path
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "${tmp_dir}"' EXIT
    archive_path="${tmp_dir}/firecracker-${FIRECRACKER_VERSION}-${INSTALL_ARCH}.tgz"

    download_archive "${archive_path}"
    extract_archive "${archive_path}" "${tmp_dir}"
    "${action}" "${tmp_dir}"
  )
}

install_pinned() {
  with_verified_archive install_verified_binaries
  verify_installed
}

install_verified_binaries() {
  local extract_dir
  extract_dir="$1"
  assert_source_binaries "${extract_dir}"
  install_binaries "${extract_dir}"
}

verify_installed_against_archive() {
  local extract_dir
  extract_dir="$1"
  assert_installed_checksums "${extract_dir}"
}

verify_installed_version() {
  assert_version "${FIRECRACKER_BIN}" "Installed Firecracker" "Firecracker ${FIRECRACKER_VERSION}"
  assert_version "${JAILER_BIN}" "Installed Firecracker jailer" "Jailer ${FIRECRACKER_VERSION}"
}

verify_installed() {
  verify_installed_version
  with_verified_archive verify_installed_against_archive
}

verify_live_process() {
  require_bin pgrep
  require_bin readlink
  require_bin sha256sum

  assert_version "${FIRECRACKER_BIN}" "Installed Firecracker" "Firecracker ${FIRECRACKER_VERSION}"

  local found pid exe_path exe live_checksum installed_checksum mismatch_count
  found=0
  mismatch_count=0
  installed_checksum="$(sha256sum "${FIRECRACKER_BIN}" | awk '{ print $1 }')"

  for pid in $(pgrep -x firecracker 2>/dev/null || true); do
    found=1
    exe_path="/proc/${pid}/exe"
    exe="$(readlink "${exe_path}" 2>/dev/null || true)"
    if [ -z "${exe}" ]; then
      echo "::error::failed to read live Firecracker executable for PID ${pid}" >&2
      mismatch_count=$((mismatch_count + 1))
      continue
    fi
    case "${exe}" in
      *" (deleted)")
        echo "::error::live Firecracker PID ${pid} executable is deleted: ${exe}" >&2
        mismatch_count=$((mismatch_count + 1))
        continue
        ;;
    esac
    live_checksum="$(sha256sum "${exe_path}" 2>/dev/null | awk '{ print $1 }' || true)"
    if [ -z "${live_checksum}" ]; then
      echo "::error::failed to hash live Firecracker executable for PID ${pid}: ${exe}" >&2
      mismatch_count=$((mismatch_count + 1))
      continue
    fi
    if [ "${live_checksum}" != "${installed_checksum}" ]; then
      echo "::error::live Firecracker PID ${pid} checksum does not match ${FIRECRACKER_BIN}: ${exe}" >&2
      mismatch_count=$((mismatch_count + 1))
      continue
    fi
    printf '%s %s\n' "${pid}" "${exe}"
  done

  if [ "${found}" -ne 1 ]; then
    error "no live Firecracker process was found"
  fi
  if [ "${mismatch_count}" -ne 0 ]; then
    error "${mismatch_count} live Firecracker process checksum check(s) failed"
  fi
}

print_constants() {
  cat <<CONSTANTS
FIRECRACKER_VERSION=${FIRECRACKER_VERSION}
FIRECRACKER_X86_64_TGZ_SHA256=${FIRECRACKER_X86_64_TGZ_SHA256}
FIRECRACKER_AARCH64_TGZ_SHA256=${FIRECRACKER_AARCH64_TGZ_SHA256}
FIRECRACKER_RELEASE_BASE_URL=${FIRECRACKER_RELEASE_BASE_URL}
INSTALL_ARCH=${INSTALL_ARCH}
INSTALL_DIR=${INSTALL_DIR}
FIRECRACKER_BIN=${FIRECRACKER_BIN}
JAILER_BIN=${JAILER_BIN}
CONSTANTS
}

case "${1:-}" in
  install)
    install_pinned
    ;;
  verify)
    verify_installed
    ;;
  verify-installed-version)
    verify_installed_version
    ;;
  verify-live-process)
    verify_live_process
    ;;
  constants)
    print_constants
    ;;
  *)
    echo "usage: $0 {install|verify|verify-installed-version|verify-live-process|constants}" >&2
    exit 2
    ;;
esac
