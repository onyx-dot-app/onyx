#!/usr/bin/env bash
# Print the current stable Chrome for Testing version.
set -euo pipefail

# Callers put the version in URLs and sed expressions, so reject any other shape.
curl --fail --silent --show-error --location --retry 3 \
  https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json \
  | jq -er '.channels.Stable.version | select(test("^[0-9]+(\\.[0-9]+){3}$"))'
