"""Shared session-workspace setup script for the Docker and Kubernetes
sandbox managers.

The script is replay-safe: the whole setup is serialized per session with an
in-sandbox ``flock``, an in-progress marker distinguishes a partial directory
from a complete workspace, and the Next.js dev server is only spawned when no
live server is already attached to the session. Re-running the script after an
interruption converges on the same completed workspace.
"""

import shlex

from onyx.server.features.build.sandbox.base import (
    BUN_CACHE_DIR,
    BUN_IMAGE_CACHE_DIR,
)
from onyx.server.features.build.sandbox.nextjs_dev import build_nextjs_start_script

SESSIONS_ROOT = "/workspace/sessions"
TEMPLATES_OUTPUTS_PATH = "/workspace/templates/outputs"
MANAGED_SKILLS_PATH = "/workspace/managed/skills"
MANAGED_USER_LIBRARY_PATH = "/workspace/managed/user_library"

# Present inside a session directory while setup is running; its presence on
# an existing directory means the workspace is partial, not ready. Legacy
# workspaces (created before the marker existed) have no marker and read as
# complete.
SETUP_IN_PROGRESS_MARKER = ".setup-in-progress"

# Last line the setup script prints. Callers MUST verify it in the exec
# output: the Kubernetes exec client returns buffered output without raising
# when its timeout lapses (and never raises on a nonzero exit), so the
# sentinel is the only reliable success signal.
WORKSPACE_SETUP_COMPLETE_SENTINEL = "ONYX_WORKSPACE_SETUP_COMPLETE"


def build_workspace_exists_check_script(session_path: str) -> str:
    """Emit ``WORKSPACE_FOUND`` only for a complete workspace: the outputs
    directory exists and no in-progress marker is present."""
    return (
        f'if [ -d "{session_path}/outputs" ] && '
        f'[ ! -f "{session_path}/{SETUP_IN_PROGRESS_MARKER}" ]; '
        f'then echo "WORKSPACE_FOUND"; else echo "WORKSPACE_MISSING"; fi'
    )


def build_session_workspace_setup_script(
    session_path: str,
    agents_md: str,
    session_opencode_config_json: str,
    nextjs_port: int | None,
) -> str:
    """Build the shell script that creates a session workspace.

    Headless callers (scheduled tasks) pass ``nextjs_port=None`` — the agent's
    tools work without a dev server.
    """
    outputs_setup = f"""
echo "Copying outputs template"
if [ -d {TEMPLATES_OUTPUTS_PATH} ]; then
    cp -r {TEMPLATES_OUTPUTS_PATH}/* {session_path}/outputs/
    # flock+sentinel: serialize concurrent session setups; .ready guards
    # against a partial cp from a previous interrupted run.
    (
        flock -x 9
        if [ ! -f {BUN_CACHE_DIR}/.ready ]; then
            echo "Bootstrapping bun cache on workspace volume..."
            rm -rf {BUN_CACHE_DIR}
            cp -r {BUN_IMAGE_CACHE_DIR} {BUN_CACHE_DIR} \\
                || {{ echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }}
            touch {BUN_CACHE_DIR}/.ready
        fi
    ) 9>{BUN_CACHE_DIR}.lock
    cd {session_path}/outputs/web && \\
        BUN_INSTALL_CACHE_DIR={BUN_CACHE_DIR} \\
        bun install --frozen-lockfile --backend=hardlink
else
    echo "Warning: outputs template not found at {TEMPLATES_OUTPUTS_PATH}"
    mkdir -p {session_path}/outputs/web
fi
"""

    nextjs_start_script = (
        build_nextjs_start_script(session_path, nextjs_port, check_node_modules=False)
        if nextjs_port is not None
        else ""
    )

    return f"""
set -e

# Serialize workspace *materialization* per session with an flock: a concurrent
# replay blocks here and then re-runs over the completed workspace, converging
# instead of racing. The dev-server launch is deliberately NOT inside this
# subshell — a backgrounded server started here would inherit fd 8 and hold the
# lock for its entire lifetime, deadlocking every later repair/restore. It runs
# after the lock releases and has its own pid-guard for idempotency.
(
flock -x 8
set -e

echo "Creating session directory: {session_path}"
mkdir -p {session_path}
touch {session_path}/{SETUP_IN_PROGRESS_MARKER}
mkdir -p {session_path}/outputs
mkdir -p {session_path}/attachments

# Setup outputs
{outputs_setup}

# DO NOT mkdir /workspace/managed/skills or /workspace/managed/user_library
# here — the push daemon swaps these paths via os.rename(symlink, mount),
# which fails if the mount is a real directory. Dangling until the first
# push lands is fine; nothing reads these during the rest of setup.
mkdir -p {session_path}/.opencode
ln -sfn {MANAGED_SKILLS_PATH} {session_path}/.opencode/skills
echo "Linked skills to {MANAGED_SKILLS_PATH}"
ln -sfn {MANAGED_USER_LIBRARY_PATH} {session_path}/user_library
echo "Linked user_library to {MANAGED_USER_LIBRARY_PATH}"

# Write agent instructions
echo "Writing AGENTS.md"
printf '%s' {shlex.quote(agents_md)} > {session_path}/AGENTS.md

printf '%s' {shlex.quote(session_opencode_config_json)} > {session_path}/opencode.json

rm -f {session_path}/{SETUP_IN_PROGRESS_MARKER}
echo "Workspace materialization complete"
) 8>{session_path}.setup.lock

# Start Next.js dev server (outside the setup lock; own pid-guard).
{nextjs_start_script}
echo "{WORKSPACE_SETUP_COMPLETE_SENTINEL}"
"""
