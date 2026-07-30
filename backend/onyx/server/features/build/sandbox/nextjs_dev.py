"""Builds the shell script that starts a session's Next.js dev server.

Shared by the Docker and Kubernetes sandbox managers so the dev-server
environment (base path, allowed dev origins) stays identical across backends.
"""

from urllib.parse import urlparse

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.server.features.build.sandbox.base import BUN_CACHE_DIR


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
cd {session_path}/outputs/web
{install_check}
export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/$(basename {session_path})/webapp"
export ONYX_WEBAPP_ALLOWED_DEV_ORIGINS="{allowed_dev_origins()}"
if grep -q "WEBAPP_ASSET_PREFIX" next.config.ts 2>/dev/null; then
    cat > next.config.ts <<'EOF'
import type {{ NextConfig }} from "next";

const webappBasePath = process.env.ONYX_WEBAPP_BASE_PATH || undefined;
const allowedDevOrigins = (process.env.ONYX_WEBAPP_ALLOWED_DEV_ORIGINS || "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {{}};

if (webappBasePath) {{
  nextConfig.basePath = webappBasePath;
  nextConfig.assetPrefix = webappBasePath;
}}

if (allowedDevOrigins.length > 0) {{
  nextConfig.allowedDevOrigins = allowedDevOrigins;
}}

export default nextConfig;
EOF
fi
echo "Starting Next.js dev server on port {nextjs_port}..."
nohup bun run dev -- -H 0.0.0.0 -p {nextjs_port} > {session_path}/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo "Next.js server started with PID $NEXTJS_PID"
echo $NEXTJS_PID > {session_path}/nextjs.pid
"""
