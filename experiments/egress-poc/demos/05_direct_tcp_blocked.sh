#!/usr/bin/env bash
# Documented mode-specific outcome:
#   Explicit:    direct TCP to api.allowed.example:80 must FAIL (L1 has no route)
#   Transparent: direct TCP succeeds because iptables DNATs to proxy:8081,
#                proxy enforces policy and the allowed host returns 200.
#
# Both outcomes are the intended security property of their respective mode.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="05 direct TCP (--noproxy)"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

# --noproxy '*' forces curl to bypass any HTTP[S]_PROXY env var.
if is_explicit; then
    dx_real curl --noproxy '*' --max-time 5 -fsS \
        http://api.allowed.example:80/ >/dev/null 2>&1
    rc=$?
    if [ $rc -eq 0 ]; then
        fail "L1 firewall failed open: direct TCP succeeded (rc=0)"
    fi
    pass
else
    # Transparent: DNAT should make this succeed (and the proxy injects auth).
    CODE=$(dx_safe curl --noproxy '*' --max-time 5 -s -o /dev/null -w '%{http_code}' http://api.allowed.example:80/ )
    case "$CODE" in
        200) pass ;;
        *) fail "transparent DNAT path did not yield 200 (got $CODE)" ;;
    esac
fi
