#!/usr/bin/env bash
# Allowed host: broker injects Authorization the sandbox never set; the
# upstream echo confirms it arrived.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="01 allowed host + credential injection"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

OUT=$(dx_safe curl -fsS https://api.allowed.example/v1/issues)
AUTH=$(printf '%s' "$OUT" | jq -r '.headers.authorization // ""' 2>/dev/null || echo "")

case "$AUTH" in
    "Bearer poc-secret-allowed-service-bearer-token")
        pass ;;
    "")
        fail "no Authorization in upstream echo; got: $OUT" ;;
    *)
        fail "unexpected Authorization: $AUTH" ;;
esac
