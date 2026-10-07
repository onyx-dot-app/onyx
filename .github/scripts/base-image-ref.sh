#!/usr/bin/env bash
# Prints the image that holds everything the component's runtime image ships
# outside its lockfiles: the pinned hardened runtime base for web and
# model-server, and for backend and the sandbox their apt stage, built here
# from the checked-out Dockerfile.
#
# usage: base-image-ref.sh <web|model-server|backend|sandbox>
#
# The hardened digests come from the environment the dhi-base-images action
# exports in CI, or straight from that action's file otherwise (a local run),
# so both scan the base the release ships. Pulling it needs `docker login
# dhi.io`.
set -euo pipefail

dhi_action=.github/actions/dhi-base-images/action.yml

component="$1"
case "${component}" in
  web)
    ref="$(printf '%s\n' "${DHI_NODE_BUILD_ARGS:-}" | sed -n 's/^NODE_RUNTIME_IMAGE=//p')"
    [ -n "${ref}" ] || ref="$(sed -n 's/^ *echo "NODE_RUNTIME_IMAGE=\(.*\)"$/\1/p' "${dhi_action}")"
    ;;
  model-server)
    ref="$(printf '%s\n' "${DHI_PYTHON_BUILD_ARGS:-}" | sed -n 's/^PYTHON_RUNTIME_IMAGE=//p')"
    [ -n "${ref}" ] || ref="$(sed -n 's/^ *echo "PYTHON_RUNTIME_IMAGE=\(.*\)"$/\1/p' "${dhi_action}")"
    ;;
  backend)
    docker build --quiet --target os --tag onyx-backend-os:audit backend >&2
    ref="onyx-backend-os:audit"
    ;;
  sandbox)
    docker build --quiet --target os --tag onyx-sandbox-os:audit backend/onyx/server/features/build/sandbox/image >&2
    ref="onyx-sandbox-os:audit"
    ;;
  *)
    echo "unknown component: ${component}" >&2
    exit 2
    ;;
esac
[ -n "${ref}" ] || { echo "no runtime base found for ${component}" >&2; exit 1; }
printf '%s\n' "${ref}"
