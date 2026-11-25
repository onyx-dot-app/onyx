#!/usr/bin/env bash
# Produce one nightly report for the Node base images outside the web OS scan.
set -euo pipefail

audit="$1"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
"${audit}" node-image-pins > "${tmp}/pins.json"
jq -er '.[] | .image' "${tmp}/pins.json" > "${tmp}/refs"
web="$(.github/scripts/base-image-ref.sh web)"
reports=()
while IFS= read -r image; do
  if [[ "${image##*@}" == "${web##*@}" ]]; then
    continue
  fi
  report="${tmp}/${image##*@}.json"
  "${audit}" image "${image}" --strict --ignore-url "" --format=json > "${report}" || {
    # A completed scan with blockers also exits nonzero.
    jq -e '.blocking | length > 0' "${report}" > /dev/null
  }
  jq -e 'has("blocking")' "${report}" > /dev/null
  reports+=("${report}")
done < "${tmp}/refs"
jq -s '{findings: map(.findings[]?), ignored: map(.ignored[]?), blocking: map(.blocking[]?)}' "${reports[@]}" < /dev/null
