#!/usr/bin/env bash
# Denied host: broker returns deny -> proxy returns 403.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="02 denied host"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

CODE=$(dx_safe curl -s -o /dev/null -w '%{http_code}' https://api.denied.example/)
case "$CODE" in
    403) pass ;;
    *) fail "expected 403, got $CODE" ;;
esac
