"""Shared helpers for webapp-preview tests.

The proxy contracts these pin (Origin/Sec-Fetch header stripping, basePath
serving) must hold identically on every sandbox backend, so the k8s and
docker suites assert them through this single implementation.

Provisioning is lazy — setup only writes ``start-webapp.sh`` — so tests stand
in for the agent and run it themselves via ``start_session_webapp``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from uuid import UUID

import httpx
import pytest

from onyx.server.features.build.sandbox.nextjs_dev import WEBAPP_PACKAGE_JSON_PATH
from onyx.server.features.build.sandbox.session_workspace import SESSIONS_ROOT
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_POLL_INTERVAL_S = 2.0

# Hard exec cap only, so a wedged bootstrap fails with diagnostics rather than
# hanging; the budget it must actually meet is WEBAPP_TOOL_START_BUDGET_S.
WEBAPP_BOOTSTRAP_TIMEOUT_S = 420.0
WEBAPP_READY_TIMEOUT_S = 300.0

# What the agent's `webapp` tool allows before it kills the bootstrap
# (START_TIMEOUT_MS in image/opencode-plugins/webapp.ts).
WEBAPP_TOOL_START_BUDGET_S = 150.0

# Neither backend's exec surfaces the script's nonzero exit, so this line is
# the only signal that the dev server actually came up.
WEBAPP_STARTED_SENTINEL = "dev server running on port"

_MAX_DIAGNOSTIC_CHARS = 4000


def truncate_output(output: str) -> str:
    if len(output) <= _MAX_DIAGNOSTIC_CHARS:
        return output
    return f"...(truncated)\n{output[-_MAX_DIAGNOSTIC_CHARS:]}"


def webapp_bootstrap_command(session_id: UUID) -> str:
    return f"bash {SESSIONS_ROOT}/{session_id}/start-webapp.sh"


def webapp_script_stat_command(session_id: UUID) -> str:
    return f'stat -c "%u:%g %a" {SESSIONS_ROOT}/{session_id}/start-webapp.sh'


def webapp_logs_command(session_id: UUID, *, lines: int = 40) -> str:
    session_path = f"{SESSIONS_ROOT}/{session_id}"
    return (
        f"for log in {session_path}/webapp-bootstrap.log {session_path}/nextjs.log; do "
        f'echo "--- $log ---"; tail -n {lines} "$log" 2>&1 || true; '
        f"done"
    )


WEBAPP_INSTALLED = "INSTALLED"


def webapp_install_check_command(session_id: UUID) -> str:
    """Echoes how far provisioning got.

    Keys on the install marker, not the scaffold: the template copy writes
    ``package.json`` before the bun install runs, so a scaffold check would
    read a failed install as success.
    """
    session_path = f"{SESSIONS_ROOT}/{session_id}"
    web_path = f"{session_path}/outputs/web"
    return (
        f"if [ -f {web_path}/node_modules/next/package.json ]; "
        f"then echo {WEBAPP_INSTALLED}; "
        f"elif [ -f {session_path}/{WEBAPP_PACKAGE_JSON_PATH} ]; "
        f"then echo SCAFFOLD_ONLY; else echo MISSING; fi"
    )


def verify_webapp_bootstrap(
    session_id: UUID,
    *,
    output: str,
    install_state: str,
    elapsed_s: float,
) -> None:
    """Fail unless the bootstrap installed, started, and did so in budget.

    Neither backend's exec raises on the script's own failure paths, so
    success has to be judged from what it printed and what it left behind.
    """
    tail = truncate_output(output)
    if install_state != WEBAPP_INSTALLED:
        pytest.fail(
            f"start-webapp.sh did not install outputs/web for session "
            f"{session_id} (state={install_state}):\n{tail}"
        )
    if WEBAPP_STARTED_SENTINEL not in output:
        pytest.fail(
            f"start-webapp.sh installed but never started a dev server for "
            f"session {session_id}:\n{tail}"
        )
    if elapsed_s > WEBAPP_TOOL_START_BUDGET_S:
        pytest.fail(
            f"start-webapp.sh took {elapsed_s:.0f}s for session {session_id}, "
            f"over the {WEBAPP_TOOL_START_BUDGET_S:.0f}s the `webapp` tool "
            f"allows before it kills the bootstrap (START_TIMEOUT_MS in "
            f"image/opencode-plugins/webapp.ts). The agent's path is broken "
            f"even though the script eventually finished."
        )


def wait_for_webapp_ready(
    user: DATestUser,
    session_id: str,
    *,
    timeout_s: float = WEBAPP_READY_TIMEOUT_S,
    diagnostics: Callable[[], str] | None = None,
) -> None:
    deadline = time.monotonic() + timeout_s
    info: dict[str, object] = {}
    while time.monotonic() < deadline:
        resp = client.get(
            f"{API_SERVER_URL}/build/sessions/{session_id}/webapp-info",
            headers=user.headers,
            cookies=user.cookies,
        )
        resp.raise_for_status()
        info = resp.json()
        if info.get("has_webapp") and info.get("ready"):
            return
        time.sleep(_POLL_INTERVAL_S)
    detail = f"\n{diagnostics()}" if diagnostics is not None else ""
    pytest.fail(f"webapp never became ready within timeout: {info}{detail}")


def proxy_get(user: DATestUser, session_id: str, path: str = "") -> httpx.Response:
    url = f"{API_SERVER_URL}/build/sessions/{session_id}/webapp"
    if path:
        url = f"{url}/{path.lstrip('/')}"
    return client.get(
        url,
        headers={
            **user.headers,
            # What a browser cors-mode fetch attaches even same-origin; the
            # proxy must strip these or Next dev 403s every /_next/* request.
            # Non-localhost on purpose: Next dev allows localhost origins by
            # default, which would mask a strip regression in CI.
            "Origin": "https://cloud.onyx.app",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
        cookies=user.cookies,
        follow_redirects=True,
    )
