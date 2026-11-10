#!/usr/bin/env bash
# Scan the browser shipped in the image, independently of Debian's inventory.
set -euo pipefail

image="$1"
inventory="$(mktemp -d)"
container=""
cleanup() {
  if [ -n "$container" ]; then docker rm "$container" >/dev/null; fi
  rm -rf "$inventory"
}
trap cleanup EXIT
container="$(docker create "$image")"
docker cp "$container:/opt/chrome/browser.cdx.json" "$inventory/browser.cdx.json"
# New Chrome advisories can precede the vulnerability database's CPE ranges.
# Require the current stable release as well as a clean vulnerability scan.
installed="$(jq -er '
  .components | select(length == 1) | .[0]
  | select(.name == "chrome" and .cpe == ("cpe:2.3:a:google:chrome:" + .version + ":*:*:*:*:*:*:*"))
  | .version
' "$inventory/browser.cdx.json")"
latest="$("$(dirname "$0")/chrome-stable-version.sh")"
if [ "$installed" != "$latest" ]; then
  echo "Sandbox Chrome ${installed} is not current stable ${latest}; run .github/scripts/update-sandbox-browser.sh on install-browser.sh." >&2
  exit 1
fi
docker_args=(--rm --env GRYPE_CHECK_FOR_APP_UPDATE=false)
if [ -n "${SSL_CERT_FILE:-}" ]; then
  docker_args+=(--mount "type=bind,source=${SSL_CERT_FILE},target=/certs/ca.pem,readonly" --env SSL_CERT_FILE=/certs/ca.pem)
fi
docker run "${docker_args[@]}" \
  --mount "type=bind,source=${inventory},target=/inventory,readonly" \
  "${BASE_IMAGE_REGISTRY:-docker.io}/anchore/grype:v0.121.1@sha256:6b06708b036f74b2cd70e94b706b4586af96d1932e6ac46255940b2e39dd44a9" \
  sbom:/inventory/browser.cdx.json --fail-on critical
