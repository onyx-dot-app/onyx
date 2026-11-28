#!/usr/bin/env bash
# Prints the appVersion for a published onyx chart: the highest stable Onyx
# tag (vX.Y.Z) among the local tags, or "latest" when there is none. This is
# the release that the default global.version "latest" images point at
# (`ods release classify` gives "latest" to the same tag). The chart takes the
# Craft Firecracker image tags from it (onyx.craftFcReleaseTag).
#
# usage: chart-app-version.sh   (run in a checkout that has all tags)
set -euo pipefail

tag="$(
  git tag --list 'v*' \
    | grep -E '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' \
    | sort -t. -k1.2,1n -k2,2n -k3,3n \
    | tail -n 1 \
    || true
)"
printf '%s\n' "${tag:-latest}"
