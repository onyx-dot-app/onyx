#!/bin/sh
# Starts the guest daemon in a sandbox container, as the sandbox user.
# Args go to guest-daemon after --container (for example --listen tcp:...,
# --key-file, --tls-cert, --tls-key). Docker runs it through
# firewall-init (entrypoint mode), which drops to uid 1000 first.
set -eu
if [ "$(id -u)" = 0 ]; then
  echo "sandbox-entrypoint: run as uid 1000, not root" >&2
  exit 1
fi
mkdir -p /tmp/onyx/tool-results /tmp/onyx/artifacts
# Chrome trusts its own NSS database, not the system bundle: add the egress
# proxy CA there too. A failure is only logged, as in a VM.
ca="${SANDBOX_PROXY_CA_BUNDLE_SRC:-/sandbox-ca/ca.crt}"
if [ -r "${ca}" ]; then
  nssdb="${HOME:-/home/sandbox}/.pki/nssdb"
  if mkdir -p "${nssdb}" &&
    { [ -f "${nssdb}/cert9.db" ] || certutil -N -d "sql:${nssdb}" --empty-password; } &&
    certutil -A -d "sql:${nssdb}" -n sandbox-proxy -t "C,," -i "${ca}"; then
    echo "sandbox-entrypoint: added the proxy CA to ${nssdb}" >&2
  else
    echo "sandbox-entrypoint: could not add the proxy CA to ${nssdb}" >&2
  fi
fi
# tini (PID 1) reaps orphaned command children; the daemon waits only for
# its own children.
exec /usr/bin/tini -s -- /usr/local/bin/guest-daemon --container "$@"
