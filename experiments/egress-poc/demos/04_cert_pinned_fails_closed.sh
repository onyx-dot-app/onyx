#!/usr/bin/env bash
# A pinned client that trusts only its own CA must reject the Onyx-issued
# leaf cert. We generate a throwaway CA in /tmp and curl with --cacert.
set -uo pipefail

export SANDBOX="${1:?sandbox name required}"
export DEMO_DESC="04 cert-pinned client fails closed"
# shellcheck source=_lib.sh
# shellcheck disable=SC1091  # dynamic path; pre-commit shellcheck runs without -x
. "$(dirname "$0")/_lib.sh"

# Generate a fresh CA inside the sandbox (idempotent).
dx_safe sh -c 'test -f /tmp/other-ca.crt || openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout /tmp/other.key -out /tmp/other-ca.crt -days 1 \
    -subj "/CN=throwaway-pin" 2>/dev/null' >/dev/null

# curl should fail the handshake; exit code is non-zero. Use dx_real (not
# dx_safe) so we get the real curl exit code, not the wrapper's.
#
# --capath /tmp is required: without it, curl falls back to the default
# capath (/etc/ssl/certs) which has the Onyx CA installed system-wide via
# update-ca-certificates, so the leaf cert would validate regardless of
# --cacert. Pointing capath at a directory with no hashed trust anchors
# (/tmp) makes --cacert the only trust source.
dx_real curl --cacert /tmp/other-ca.crt --capath /tmp \
    --max-time 5 -fsS https://api.allowed.example/ >/dev/null 2>&1
rc=$?
if [ $rc -eq 0 ]; then
    fail "curl succeeded against pinned CA (rc=0); MITM cert was accepted"
fi
pass
