#!/usr/bin/env bash
# Audit each Node runtime and the base images outside the web OS scan.
set -euo pipefail

audit="$1"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
"${audit}" node-image-pins > "${tmp}/pins.json"
jq -er '.[] | .image' "${tmp}/pins.json" > "${tmp}/refs"
web="$(.github/scripts/base-image-ref.sh web)"
reports=()
: > "${tmp}/runtimes.jsonl"
while IFS= read -r image; do
  version="$(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --entrypoint node "${image}" --version)"
  jq -ce --arg image "${image}" --arg version "${version}" \
    '.[] | select(.image == $image) | . + {version: $version}' "${tmp}/pins.json" >> "${tmp}/runtimes.jsonl"
  if [[ "${image##*@}" == "${web##*@}" ]]; then
    continue
  fi
  report="${tmp}/${image##*@}.json"
  "${audit}" image "${image}" --strict --ignore-url "" --format=json > "${report}" || {
    # A completed scan with blockers also exits nonzero.
    jq -e '.blocking | length > 0' "${report}" > /dev/null
  }
  jq -e 'has("blocking")' "${report}" > /dev/null
  jq --arg image "${image}" '.blocking = [.blocking[]? | . + {image: $image}]' "${report}" > "${report}.labeled"
  reports+=("${report}.labeled")
done < "${tmp}/refs"
jq -s . "${tmp}/runtimes.jsonl" | "${audit}" node-runtimes > "${tmp}/runtime-report.json"
reports+=("${tmp}/runtime-report.json")
jq -s '{scanned_packages: map(.scanned_packages[]?), findings: map(.findings[]?), ignored: map(.ignored[]?), blocking: map(.blocking[]?)}' "${reports[@]}" < /dev/null
