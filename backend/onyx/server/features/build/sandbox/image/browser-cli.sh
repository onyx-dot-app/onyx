#!/bin/bash
# `browser` — wraps `agent-browser` so the Craft agent can drive a browser in the
# locked-down pod: pins this session and supplies the env the bare binary needs.
# A real PATH executable, not an alias — opencode's bash tool is non-interactive
# (no ~/.bashrc / alias expansion).
set -euo pipefail

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
