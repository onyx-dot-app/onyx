"""Shared helpers for webapp-preview tests.

The proxy contracts these pin (Origin/Sec-Fetch header stripping, basePath
serving) must hold identically on every sandbox backend, so the k8s and
docker suites assert them through this single implementation.

Webapp provisioning is lazy: session setup only writes ``start-webapp.sh``,
and nothing scaffolds ``outputs/web`` or starts a dev server until the agent's
`webapp` tool runs it. Tests stand in for the agent by running that script
themselves — see each backend's ``start_session_webapp``.
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

# Cold path: template copy, bun-cache bootstrap, install, then a Next dev boot.
# All of it used to happen during provisioning, outside the test's own clock.
# This is only the hard exec cap, so a wedged bootstrap fails with diagnostics
# instead of hanging; the budget the bootstrap must actually meet is below.
WEBAPP_BOOTSTRAP_TIMEOUT_S = 420.0
WEBAPP_READY_TIMEOUT_S = 300.0

# What the agent's `webapp` tool allows before it kills the bootstrap
# (START_TIMEOUT_MS in image/opencode-plugins/webapp.ts). Tests run the script
# directly, so without asserting this a cold path that creeps past it stays
# green here while being broken for every agent.
WEBAPP_TOOL_START_BUDGET_S = 150.0

# Last line the bootstrap prints on success. It is the only signal either
# backend gets: neither exec surfaces the script's nonzero exit, so a dev
# server that failed to boot is otherwise indistinguishable from one that did.
WEBAPP_STARTED_SENTINEL = "dev server running on port"

# Bootstrap output is unbounded (a full bun install); cap what a failure
# message carries.
_MAX_DIAGNOSTIC_CHARS = 4000


def truncate_output(output: str) -> str:
    """Last chunk of command output, for failure messages."""
    if len(output) <= _MAX_DIAGNOSTIC_CHARS:
        return output
    return f"...(truncated)\n{output[-_MAX_DIAGNOSTIC_CHARS:]}"


def webapp_bootstrap_command(session_id: UUID) -> str:
    """In-sandbox command that lazily scaffolds and starts the webapp."""
    return f"bash {SESSIONS_ROOT}/{session_id}/start-webapp.sh"


def webapp_script_stat_command(session_id: UUID) -> str:
    """In-sandbox command printing ``<uid>:<gid> <mode>`` for the bootstrap script."""
    return f'stat -c "%u:%g %a" {SESSIONS_ROOT}/{session_id}/start-webapp.sh'


def webapp_logs_command(session_id: UUID, *, lines: int = 40) -> str:
    """In-sandbox command dumping both webapp logs, for failure diagnostics."""
    session_path = f"{SESSIONS_ROOT}/{session_id}"
    return (
        f"for log in {session_path}/webapp-bootstrap.log {session_path}/nextjs.log; do "
        f'echo "--- $log ---"; tail -n {lines} "$log" 2>&1 || true; '
        f"done"
    )


WEBAPP_INSTALLED = "INSTALLED"


def webapp_install_check_command(session_id: UUID) -> str:
    """In-sandbox command echoing how far webapp provisioning actually got.

    The scaffold alone is not enough to distinguish success: the template copy
    writes ``package.json`` before the bun install runs, and neither backend's
    exec raises on a nonzero exit or a lapsed timeout. Checking the install
    marker is what makes a failed install loud instead of green.
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

    Shared by both backends because neither exec raises on the script's own
    failure paths, so the test has to judge success from what the script
    printed and what it left behind.
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
