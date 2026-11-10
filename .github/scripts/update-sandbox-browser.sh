#!/usr/bin/env bash
# Pin each given install-browser.sh to the current stable Chrome for Testing.
# Prints the new version when a file changed, and nothing when all are current.
set -euo pipefail

if ! latest="$(curl --fail --silent --show-error --location --retry 3 \
  https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json \
  | jq -er '.channels.Stable.version | select(test("^[0-9]+(\\.[0-9]+){3}$"))')"; then
  echo "Could not read the current stable Chrome version." >&2
  exit 1
fi

stale=()
for file in "$@"; do
  if ! grep -qxF "version=${latest}" "$file"; then
    stale+=("$file")
  fi
done
if [ "${#stale[@]}" -eq 0 ]; then
  exit 0
fi

# Chrome for Testing publishes no checksums, so hash the archives themselves.
checksum() {
  curl --fail --silent --show-error --location --retry 3 \
    "https://storage.googleapis.com/chrome-for-testing-public/${latest}/$1/chrome-$1.zip" \
    | sha256sum | cut -d' ' -f1
}
amd64="$(checksum linux64)"
arm64="$(checksum linux-arm64)"

for file in "${stale[@]}"; do
  sed -E -i.bak \
    -e "s/^version=.*/version=${latest}/" \
    -e "/^  amd64\)/,/;;/ s/checksum=.*/checksum=${amd64}/" \
    -e "/^  arm64\)/,/;;/ s/checksum=.*/checksum=${arm64}/" \
    "$file"
  rm "${file}.bak"
  # A reshaped install-browser.sh must fail here, not ship a partial pin.
  for pin in "version=${latest}" "    checksum=${amd64}" "    checksum=${arm64}"; do
    if [ "$(grep -cxF "$pin" "$file")" -ne 1 ]; then
      echo "Could not pin ${pin%%=*} in ${file}." >&2
      exit 1
    fi
  done
done
echo "$latest"
