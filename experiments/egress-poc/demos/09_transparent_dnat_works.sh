#!/usr/bin/env bash
# Transparent-only: prove the iptables DNAT-to-bridge-IP path actually works
# end-to-end -- the sandbox's HTTPS request reaches the proxy, the proxy
# terminates TLS with the Onyx-issued leaf, and the upstream returns 200.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="09 transparent DNAT works"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

if is_explicit; then
    skip "transparent-only demo"
fi

# Two assertions:
#  1. curl returns 200 (TLS terminates with our leaf signed by the Onyx CA).
#  2. curl -v shows the issued cert subject contains api.allowed.example
#     (proves the leaf was minted by mitmproxy, not a real TLS upstream).
CODE=$(dx_safe curl -s -o /dev/null -w '%{http_code}' https://api.allowed.example/)
if [[ "$CODE" != "200" ]]; then
    fail "expected 200, got $CODE"
fi

SUBJECT=$(dx_safe sh -c 'curl -v https://api.allowed.example/ 2>&1' \
    | grep -E "subject:|common name:" | head -1)
if [[ -z "$SUBJECT" ]]; then
    fail "no TLS subject line in curl verbose output"
fi
if ! echo "$SUBJECT" | grep -qi "api.allowed.example"; then
    fail "TLS subject did not match api.allowed.example: $SUBJECT"
fi
pass
