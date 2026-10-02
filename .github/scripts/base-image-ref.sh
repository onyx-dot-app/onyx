#!/usr/bin/env bash
# Prints the image that holds everything the component's runtime image ships
# outside its lockfiles: the pinned runtime base for web and model-server, and
# for backend its apt stage, built here from the checked-out Dockerfile.
#
# usage: base-image-ref.sh <web|model-server|backend>
#
# The DHI digests come from the environment the dhi-base-images action exports;
# without it the Dockerfile's public default applies, as in the build itself.
set -euo pipefail

component="$1"
case "${component}" in
  web)
    ref="$(printf '%s\n' "${DHI_NODE_BUILD_ARGS:-}" | sed -n 's/^NODE_RUNTIME_IMAGE=//p')"
    [ -n "${ref}" ] || ref="$(sed -n 's/^ARG NODE_RUNTIME_IMAGE=//p' web/Dockerfile)"
    ;;
  model-server)
    ref="$(printf '%s\n' "${DHI_PYTHON_BUILD_ARGS:-}" | sed -n 's/^PYTHON_RUNTIME_IMAGE=//p')"
    [ -n "${ref}" ] || ref="$(sed -n 's/^ARG PYTHON_RUNTIME_IMAGE=//p' backend/Dockerfile.model_server)"
    ;;
  backend)
    docker build --quiet --target os --tag onyx-backend-os:audit backend >&2
    ref="onyx-backend-os:audit"
    ;;
  *)
    echo "unknown component: ${component}" >&2
    exit 2
    ;;
esac
printf '%s\n' "${ref//\$\{BASE_IMAGE_REGISTRY\}/docker.io}"
