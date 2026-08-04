"""Builds the shell script that starts a session's Next.js dev server.

Shared by the Docker and Kubernetes sandbox managers so the dev-server
environment (base path, allowed dev origins) stays identical across backends.
"""

from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR

_TEMPLATE_NEXT_CONFIG = (
    Path(__file__).parent / "image" / "templates" / "outputs" / "web" / "next.config.ts"
)


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
