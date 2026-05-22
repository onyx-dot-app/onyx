#!/usr/bin/env bash
# Missing SNI: the proxy's tls_clienthello hook aborts the connection.
#
# We test on whatever TLS-speaking port the sandbox can reach:
#   Transparent: any port 443 (DNAT-redirected to proxy:8443)
#   Explicit:    SKIP -- the explicit listener on 8444 is HTTP-proxy, not TLS;
#                exercising "missing SNI" through a CONNECT tunnel needs a
#                custom client, out of v0 scope.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="08 missing SNI blocked"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

if is_explicit; then
    skip "explicit mode would require a CONNECT-then-raw-TLS client"
fi

# Transparent path: openssl s_client to any TCP/443 destination gets DNAT'd
# to proxy:8443; with -noservername the ClientHello has no SNI.
OUT=$(dx_safe sh -c 'openssl s_client -connect 1.2.3.4:443 -noservername </dev/null 2>&1')
if echo "$OUT" | grep -qE "alert|error|HANDSHAKE_FAILURE|tlsv1|SSL_ERROR|connect:errno"; then
    pass
else
    fail "TLS without SNI did not fail at the proxy: $OUT"
fi
