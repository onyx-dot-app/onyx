#!/bin/bash
# `browser` — wraps `agent-browser` so the Craft agent can drive a browser in the
# locked-down pod: pins this session and supplies the env the bare binary needs.
# A real PATH executable, not an alias — opencode's bash tool is non-interactive
# (no ~/.bashrc / alias expansion).
set -euo pipefail

CA_BUNDLE="${SANDBOX_PROXY_CA_BUNDLE_DST:-/etc/ssl/sandbox/ca-bundle.crt}"
NSSDB="$HOME/.pki/nssdb"

# Trust the egress proxy's MITM CA in Chromium's NSS db (it reads trust only from
# there, not env), else every HTTPS page fails ERR_CERT_AUTHORITY_INVALID.
# Idempotent. The bundle is many roots with the Onyx CA last; `certutil -A` takes
# only the first cert, so split and import each. Runs once (sentinel-guarded).
if [ -f "$CA_BUNDLE" ] && [ ! -f "$NSSDB/.proxy-ca-imported" ]; then
    mkdir -p "$NSSDB"
    [ -f "$NSSDB/cert9.db" ] || certutil -d "sql:$NSSDB" -N --empty-password
    SPLITDIR="$(mktemp -d)"
    csplit -z -f "$SPLITDIR/ca-" -b "%03d.pem" "$CA_BUNDLE" "/BEGIN CERTIFICATE/" "{*}" >/dev/null 2>&1
    imported=0
    for f in "$SPLITDIR"/ca-*.pem; do
        if [ -f "$f" ] && certutil -d "sql:$NSSDB" -A -t "C,," -n "proxy-$(basename "$f" .pem)" -i "$f" 2>/dev/null; then
            imported=$((imported + 1))
        fi
    done
    rm -rf "$SPLITDIR"
    # Only commit the sentinel once at least one cert landed — otherwise a bad
    # bundle would be skipped forever, re-creating the ERR_CERT_AUTHORITY_INVALID
    # this block exists to prevent.
    if [ "$imported" -gt 0 ]; then
        touch "$NSSDB/.proxy-ca-imported"
    else
        echo "browser: CA bundle present but no certs imported; HTTPS via the proxy may fail" >&2
    fi
fi

# Chromium needs --no-sandbox (pod drops caps/seccomp) and the proxy as a FLAG
# (it ignores *_PROXY env; userinfo stripped — proxy authorizes by source IP);
# agent-browser otherwise launches a non-installed Chrome-for-Testing.
CLEAN_PROXY="$(printf '%s' "${HTTPS_PROXY:-${HTTP_PROXY:-}}" | sed -E 's#^([a-z]+://)?[^@/]*@#\1#')"
# No proxy → an empty --proxy-server= sends Chromium direct, which egress blocks; fail fast.
if [ -z "${AGENT_BROWSER_ARGS:-}" ] && [ -z "$CLEAN_PROXY" ]; then
    echo "browser: no egress proxy configured (HTTPS_PROXY/HTTP_PROXY unset)" >&2
    exit 1
fi
export AGENT_BROWSER_EXECUTABLE_PATH="${AGENT_BROWSER_EXECUTABLE_PATH:-/usr/bin/chromium}"
export AGENT_BROWSER_ARGS="${AGENT_BROWSER_ARGS:---no-sandbox,--proxy-server=${CLEAN_PROXY},--proxy-bypass-list=127.0.0.1;localhost,--disable-dev-shm-usage,--disable-gpu}"

# Pin this session's browser (one pod hosts many; cwd is /workspace/sessions/<id>/).
SESSION_ID="$(pwd | sed -n 's#.*/sessions/\([0-9a-fA-F-]\{36\}\).*#\1#p')"
if [ -n "$SESSION_ID" ]; then
    exec agent-browser --session "$SESSION_ID" "$@"
fi
exec agent-browser "$@"
