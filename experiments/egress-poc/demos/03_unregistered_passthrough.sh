#!/usr/bin/env bash
# Unregistered host with EGRESS_DEFAULT_DENY=false (the compose default):
# forwarded as pass-through with no Authorization injected. The upstream
# echo must show no broker-injected Authorization.
#
# To test EGRESS_DEFAULT_DENY=true, redeploy the broker with that env and
# rerun this demo manually -- it will return 403 instead.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="03 unregistered host passthrough"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

OUT=$(dx_safe curl -fsS https://api.unregistered.example/some/path)
AUTH=$(printf '%s' "$OUT" | jq -r '.headers.authorization // ""' 2>/dev/null || echo "")
PATH_ECHO=$(printf '%s' "$OUT" | jq -r '.path // ""' 2>/dev/null || echo "")

if [[ -z "$PATH_ECHO" ]]; then
    fail "no upstream echo received; got: $OUT"
fi
if [[ -n "$AUTH" ]]; then
    fail "unexpected Authorization injected for unregistered host: $AUTH"
fi
pass
