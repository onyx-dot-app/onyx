#!/usr/bin/env bash
# Runs run.py in a throwaway X11 + D-Bus + GNOME Keyring session, like a CI runner.
# Usage: desktop-v2/tests/smoke/run-linux.sh --server <url> [run.py options]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

if [[ "${ONYX_SMOKE_INNER:-}" != 1 ]]; then
  export ONYX_SMOKE_INNER=1
  exec xvfb-run --auto-servernum --server-args="-screen 0 1440x900x24" \
    dbus-run-session -- "$0" "$@"
fi

# A private keyring for this run, unlocked with an empty password.
keyring_home="$(mktemp -d)"
export XDG_DATA_HOME="$keyring_home"
export XDG_RUNTIME_DIR="$keyring_home/run"
mkdir -m 700 "$XDG_RUNTIME_DIR" "$keyring_home/keyrings"
# Without an existing default collection, the daemon asks a GUI prompter to create
# one and every store blocks. A plain-text keyring file has no password to prompt for.
printf '[keyring]\ndisplay-name=login\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n' \
  >"$keyring_home/keyrings/login.keyring"
printf 'login' >"$keyring_home/keyrings/default"
chmod 600 "$keyring_home/keyrings/"*
printf '' | gnome-keyring-daemon --unlock --components=secrets >/dev/null
printf 'probe' | secret-tool store --label=probe onyx-smoke probe
secret-tool clear onyx-smoke probe

# Launcher corners and focus behave more like a desktop with a window manager.
if command -v openbox >/dev/null; then openbox >/dev/null 2>&1 & fi

exec python3 -u "$here/run.py" "$@"
