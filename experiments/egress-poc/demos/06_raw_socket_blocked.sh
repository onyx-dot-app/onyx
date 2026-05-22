#!/usr/bin/env bash
# Raw socket to an arbitrary IP:
#   Explicit:    OSError (network unreachable, L1 firewall)
#   Transparent: redirected by iptables to proxy:8443, but the TLS handshake
#                carries no SNI -> proxy denies with no_sni audit event
#                (handshake fails on the sandbox side).
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="06 raw socket to random IP"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

# openssl s_client -noservername clears SNI; -verify_return_error makes
# any TLS error fatal. We send EOF immediately via </dev/null so the
# handshake either completes or fails fast.
if is_explicit; then
    # Explicit: connection itself should fail (no route).
    if dx_safe python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('1.1.1.1', 443))
except OSError as e:
    print('expected_failure:', e)
    sys.exit(0)
print('UNEXPECTED_SUCCESS'); sys.exit(1)
" | grep -q expected_failure; then
        pass
    fi
    fail "raw TCP to 1.1.1.1:443 was not blocked"
else
    # Transparent: TCP connect succeeds (DNAT); TLS handshake fails on no SNI.
    OUT=$(dx_safe sh -c 'openssl s_client -connect 1.1.1.1:443 -noservername -verify_return_error </dev/null 2>&1')
    if echo "$OUT" | grep -qE "alert|error|HANDSHAKE_FAILURE|tlsv1|SSL_ERROR"; then
        pass
    else
        fail "TLS handshake with empty SNI did not fail: $OUT"
    fi
fi
