#!/usr/bin/env bash
# Bad session token in Proxy-Authorization -> 407 from the proxy on CONNECT.
# Transparent mode SKIPs: it doesn't use Proxy-Authorization (auth model is
# source-IP / pod-identity, designed in V1).
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="07 bad session token -> 407"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

if is_transparent; then
    skip "no Proxy-Authorization in transparent mode"
fi

# Override the env-supplied proxy URLs with a bogus token. We derive the
# proxy host:port from $HTTPS_PROXY at runtime so the same script works
# whether the proxy is reached via a Service DNS name (compose) or via
# loopback (K8s sidecar). Both upper- and lower-case env vars must be set:
# curl reads https_proxy (lowercase) for HTTPS URLs and would otherwise
# inherit the good token from the container env.
#
# We use %{http_connect}, not %{http_code}: a 407 on the CONNECT tunnel
# means the inner HTTP request never happens, so http_code is 000. The
# proxy's status code lives in http_connect.
# shellcheck disable=SC2016  # single quotes are intentional: $HTTPS_PROXY must expand inside the sandbox, not on the host
CODE=$(dx_safe sh -c '
    BAD="http://session:wrong-token@${HTTPS_PROXY##*@}"
    HTTPS_PROXY="$BAD" https_proxy="$BAD" \
        curl -s -o /dev/null -w "%{http_connect}" https://api.allowed.example/
')
case "$CODE" in
    407) pass ;;
    *)   fail "expected 407, got $CODE" ;;
esac
