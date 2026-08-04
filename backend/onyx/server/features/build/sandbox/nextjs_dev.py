"""Builds the shell script that starts a session's Next.js dev server.

Shared by the Docker and Kubernetes sandbox managers so the dev-server
environment (base path, allowed dev origins) stays identical across backends.
"""

from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR, BUN_IMAGE_CACHE_DIR

_TEMPLATE_NEXT_CONFIG = (
    Path(__file__).parent / "image" / "templates" / "outputs" / "web" / "next.config.ts"
)

# Canonical scaffold marker shared by bootstrap, restore, and API detection.
WEBAPP_PACKAGE_JSON_PATH = "outputs/web/package.json"


def webapp_base_path(session_id: UUID | str) -> str:
    """Base path a session's Next.js dev server serves under.

    Mirrored by the start script below, the template next.config.ts cwd
    fallback, and the preview proxy's upstream path.
    """
    return f"/api/build/sessions/{session_id}/webapp"


def allowed_dev_origins() -> str:
    """Hostname(s) allowed by Next dev's cross-origin check, comma-separated.

    Next 16 `allowedDevOrigins` entries are hostnames (no scheme/port); the
    deployment origin varies per install, so it is derived from WEB_DOMAIN.
    """
    return urlparse(WEB_DOMAIN).hostname or ""


def build_nextjs_start_script(
    session_path: str,
    nextjs_port: int,
    check_node_modules: bool = False,
) -> str:
    """Builds shell script to start the NextJS dev server.

    Args:
        session_path: Path to the session directory (should be shell-safe).
        nextjs_port: Port number for the NextJS dev server.
        check_node_modules: If True, check for node_modules and run bun install
            if missing.

    Returns:
        Shell script string to start the NextJS server.
    """
    # Read the template rather than duplicate it, so the two can't drift.
    template_next_config = _TEMPLATE_NEXT_CONFIG.read_text().strip()

    install_check = ""
    if check_node_modules:
        install_check = f"""
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies with bun..."
    BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
        bun install --frozen-lockfile --backend=hardlink
fi
"""

    return f"""
set -e
# Read by the template's `dev` script so a `bun run dev` the agent runs by
# hand still binds the port the preview proxy routes to.
echo {nextjs_port} > {session_path}/.nextjs-port
# Replay safety: a live server already attached to this session keeps its
# port; spawning a second one would fail to bind and leave a zombie. The
# check-and-spawn is serialized under its own flock so two replays (e.g. a
# timed-out setup still running beside its retry) can't both spawn, and the
# guard verifies process identity via cwd — PIDs recycle in a pod full of
# short-lived tool processes, so a stale nextjs.pid could otherwise match an
# unrelated live process and skip the spawn forever.
(
flock -x 9
NEXTJS_PID=""
if [ -f {session_path}/nextjs.pid ]; then
    NEXTJS_PID="$(cat {session_path}/nextjs.pid)"
fi
if [ -n "$NEXTJS_PID" ] && kill -0 "$NEXTJS_PID" 2>/dev/null && \
   [ "$(readlink /proc/$NEXTJS_PID/cwd 2>/dev/null)" = "{session_path}/outputs/web" ]; then
    echo "Next.js server already running (PID $NEXTJS_PID); reusing"
else
cd {session_path}/outputs/web
{install_check}
export ONYX_WEBAPP_PORT={nextjs_port}
export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/$(basename {session_path})/webapp"
export ONYX_WEBAPP_ALLOWED_DEV_ORIGINS="{allowed_dev_origins()}"
if grep -q "WEBAPP_ASSET_PREFIX" next.config.ts 2>/dev/null; then
    cat > next.config.ts <<'EOF'
{template_next_config}
EOF
fi
# The template's `dev` script resolves ONYX_WEBAPP_PORT itself; a second -p
# would collide with its own. But a `dev` script without the marker (legacy
# scaffold, or rewritten by the agent) ignores the env var and would bind
# 3000, so pass the port explicitly for those.
PORT_FLAG=""
if ! grep -q "ONYX_WEBAPP_PORT" package.json 2>/dev/null; then
    PORT_FLAG="-p {nextjs_port}"
fi
echo "Starting Next.js dev server on port {nextjs_port}..."
# 9>&-: the server must not inherit the lock fd, or it would hold the
# check-and-spawn lock for its entire lifetime.
nohup bun run dev -- -H 0.0.0.0 $PORT_FLAG > {session_path}/nextjs.log 2>&1 9>&- &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"
echo $NEXTJS_PID > {session_path}/nextjs.pid
fi
) 9>{session_path}.nextjs.lock
"""


def build_webapp_bootstrap_script(session_path: str, nextjs_port: int) -> str:
    """Builds the self-contained, agent-facing script written to
    ``sessions/$session_id/start-webapp.sh``. It must stay self-contained (no
    CLI wrapper, no backend round-trip); its output is plain-English guidance
    because an LLM agent is the only reader.
    """
    start_script = build_nextjs_start_script(
        session_path, nextjs_port, check_node_modules=True
    )

    return f"""#!/bin/bash
SESSION_PATH={session_path}
PORT={nextjs_port}

(
    set -e
    trap 'echo "bootstrap failed - read the error above, fix, and re-run bash start-webapp.sh" >&2' ERR

    flock -x 9

    if [ ! -f "$SESSION_PATH/{WEBAPP_PACKAGE_JSON_PATH}" ]; then
        echo "Copying outputs template"
        if [ -d /workspace/templates/outputs ]; then
            cp -r /workspace/templates/outputs/* "$SESSION_PATH/outputs/"
            # flock+sentinel: serialize concurrent bun-cache bootstraps;
            # .ready guards against a partial cp from a previous interrupted run.
            (
                flock -x 8
                if [ ! -f {BUN_CACHE_DIR}/.ready ]; then
                    echo "Bootstrapping bun cache on workspace volume..."
                    rm -rf {BUN_CACHE_DIR}
                    cp -r {BUN_IMAGE_CACHE_DIR} {BUN_CACHE_DIR} \\
                        || {{ echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }}
                    touch {BUN_CACHE_DIR}/.ready
                fi
            ) 8>{BUN_CACHE_DIR}.lock
            echo "Installing dependencies with bun..."
            (cd "$SESSION_PATH/outputs/web" && \\
                BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
                bun install --frozen-lockfile --backend=hardlink)
        else
            echo "Warning: outputs template not found at /workspace/templates/outputs"
            mkdir -p "$SESSION_PATH/outputs/web"
        fi
    fi

    # The embedded start script opens its own fd-9 subshell on
    # {session_path}.nextjs.lock, which shadows this outer fd 9 for anything
    # spawned inside it (including the nohup'd dev server, which already
    # closes 9>&- itself). So the dev server never sees this .webapp.lock fd
    # and can't hold it open for its lifetime; no extra fd-closing needed here.
    {start_script}
) 9>"$SESSION_PATH/.webapp.lock"
if [ "$?" -ne 0 ]; then
    exit 1
fi

echo "Waiting for the dev server to become ready..."
DEADLINE=$((SECONDS + 90))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    if curl -s -o /dev/null --noproxy '*' --max-time 2 "http://127.0.0.1:$PORT/"; then
        echo "web app dev server running on port $PORT - app dir: outputs/web, logs: nextjs.log. It hot-reloads on file changes and never needs 'bun run dev' run by hand."
        exit 0
    fi
    sleep 1
done

echo "server did not become ready - check nextjs.log; if it crashed, fix the error and re-run bash start-webapp.sh" >&2
echo "--- last 30 lines of nextjs.log ---" >&2
tail -n 30 "$SESSION_PATH/nextjs.log" 2>/dev/null >&2 || true
exit 1
"""


# Restore-script sentinels: the k8s exec client returns buffered output
# without raising on timeout or nonzero exit, so callers verify one of these
# appeared instead of trusting a clean return.
WEBAPP_AUTOSTART_SENTINEL = "ONYX_WEBAPP_AUTOSTART"
WEBAPP_ABSENT_SENTINEL = "ONYX_WEBAPP_ABSENT"


def build_webapp_restore_script(session_path: str, nextjs_port: int) -> str:
    """Builds the shell script both sandbox managers run after a snapshot
    restore.

    Ports change across sleep/wake, so the script is always rewritten. Auto-starts the dev server only if the restored snapshot
    actually contains a webapp (``outputs/web/package.json``), and backgrounds
    it so wake isn't blocked on a cold bun install (node_modules is excluded
    from snapshots). Echoes exactly one of the sentinels above on completion;
    they are diagnostics for Docker and the success signal for Kubernetes.
    """
    write_snippet = build_webapp_script_write_snippet(session_path, nextjs_port)
    return f"""
set -e
{write_snippet}
if [ -f {session_path}/{WEBAPP_PACKAGE_JSON_PATH} ]; then
    nohup bash {session_path}/start-webapp.sh > {session_path}/webapp-bootstrap.log 2>&1 &
    echo "{WEBAPP_AUTOSTART_SENTINEL}"
else
    echo "{WEBAPP_ABSENT_SENTINEL}"
fi
"""


def build_webapp_script_write_snippet(session_path: str, nextjs_port: int) -> str:
    """Builds a shell snippet (no shebang, no ``set -e``) that writes the
    ``chmod 444`` bootstrap script to the session root.

    Called from session setup and from restore (with the re-allocated port).
    Pinned name/signature: both sandbox managers' restore paths call this
    directly from ``onyx.server.features.build.sandbox.nextjs_dev``.
    """
    script = build_webapp_bootstrap_script(session_path, nextjs_port)
    escaped_script = script.replace("'", "'\\''")

    return f"""
# chmod 444 blocks in-place overwrite, so a rewrite (e.g. on restore) must
# unlink before writing.
rm -f {session_path}/start-webapp.sh
printf '%s' '{escaped_script}' > {session_path}/start-webapp.sh
chmod 444 {session_path}/start-webapp.sh
"""
