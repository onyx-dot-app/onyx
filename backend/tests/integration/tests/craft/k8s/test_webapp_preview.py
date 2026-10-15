"""Webapp preview behavior against a real Next dev server.

Pins the Next-side contracts the preview fixes depend on, which unit tests
cannot see: the dev-resource origin gate and basePath serving.
"""

from __future__ import annotations

import shlex

import pytest
from kubernetes import client

from onyx.server.features.build.configs import (
    SANDBOX_NAMESPACE,
)
from onyx.server.features.build.sandbox.manager import SandboxManager
from tests.common.craft.payloads import default_llm_config
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    PoolSession,
    pod_exec,
    session_webapp_logs,
    start_session_webapp,
)
from tests.integration.tests.craft.webapp_preview import (
    proxy_get,
    wait_for_webapp_ready,
    webapp_script_stat_command,
)

pytestmark = [
    # Preview tests need a dev server; pool sessions are headless by default.
    pytest.mark.parametrize(
        "pool_session",
        [pytest.param({"headless": False}, id="interactive")],
        indirect=True,
    ),
]


@pytest.fixture
def ready_webapp_session(
    pool_session: PoolSession,
    pool_api_user: DATestUser,
    k8s_client: client.CoreV1Api,
) -> PoolSession:
    """A pool session whose dev server is up and serving.

    Provisioning writes start-webapp.sh but scaffolds nothing, so the fixture
    runs it the way the agent's `webapp` tool would.
    """
    bootstrap_output = start_session_webapp(
        k8s_client, pool_session.pod_name, pool_session.session_id
    )
    wait_for_webapp_ready(
        pool_api_user,
        str(pool_session.session_id),
        diagnostics=lambda: (
            f"--- start-webapp.sh ---\n{bootstrap_output}\n"
            + session_webapp_logs(
                k8s_client, pool_session.pod_name, pool_session.session_id
            )
        ),
    )
    return pool_session


def test_setup_writes_read_only_webapp_script(
    pool_session: PoolSession,
    k8s_client: client.CoreV1Api,
) -> None:
    """Setup's only webapp artifact, written through the k8s exec path.

    Mode 444 keeps a stray redirect from replacing the fixed webapp launcher.
    """
    stat_line = pod_exec(
        k8s_client,
        pool_session.pod_name,
        SANDBOX_NAMESPACE,
        webapp_script_stat_command(pool_session.session_id),
    ).strip()
    assert stat_line == "1000:1000 444", stat_line


def test_preview_serves_at_base_path_and_reports_ready(
    ready_webapp_session: PoolSession,
    pool_api_user: DATestUser,
) -> None:
    """``ready`` flips true and the route users actually load returns 200."""
    resp = proxy_get(pool_api_user, str(ready_webapp_session.session_id))
    assert resp.status_code == 200, resp.text[:500]


def test_dev_resources_not_blocked_by_origin_gate(
    ready_webapp_session: PoolSession,
    pool_api_user: DATestUser,
) -> None:
    """A browser-shaped dev-resource request must not hit Next's cross-origin
    403 (``blockCrossSiteDEV`` rejects /_next/* when the Origin hostname is
    not allowlisted — the exact failure from the 2026-07-06 incident)."""
    resp = proxy_get(
        pool_api_user,
        str(ready_webapp_session.session_id),
        "_next/static/onyx-origin-gate-probe.js",
    )
    # 404 for a nonexistent asset is fine; the gate rejects before routing,
    # so a 403 means Origin/sec-fetch-* leaked through the proxy or the
    # allowlist regressed on a Next upgrade.
    assert resp.status_code != 403, resp.text[:500]


def test_cleanup_stops_nextjs_and_reuses_its_preview_port(
    ready_webapp_session: PoolSession,
    pool_api_user: DATestUser,
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    sandbox_id, session_id, pod_name = ready_webapp_session
    session_root = f"/workspace/sessions/{session_id}"
    recorded = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"cat {session_root}/nextjs.pid {session_root}/.nextjs-port",
    ).splitlines()
    old_pid, port = (int(value) for value in recorded)
    assert proxy_get(pool_api_user, str(session_id)).status_code == 200
    recorded_pgid = pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        f"python3 -c 'import os; print(os.getpgid({old_pid}))'",
    ).strip()
    assert int(recorded_pgid) == old_pid

    try:
        k8s_manager.cleanup_session_workspace(sandbox_id, session_id)
        bind_probe = (
            "import socket; s = socket.socket(); "
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
            f's.bind(("0.0.0.0", {port})); s.close(); print("PORT_FREE")'
        )
        released = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"test ! -e {session_root} && test ! -e /proc/{old_pid}/cwd && "
            f"python3 -c {shlex.quote(bind_probe)}",
        )
        assert released.strip() == "PORT_FREE"

        k8s_manager.setup_session_workspace(
            sandbox_id=sandbox_id,
            session_id=session_id,
            llm_config=default_llm_config(),
            nextjs_port=port,
            connectable_apps_section="",
        )
        start_session_webapp(k8s_client, pod_name, session_id)
        wait_for_webapp_ready(pool_api_user, str(session_id))
        assert proxy_get(pool_api_user, str(session_id)).status_code == 200
        reused = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"cat {session_root}/nextjs.pid {session_root}/.nextjs-port",
        ).splitlines()
        new_pid, reused_port = (int(value) for value in reused)
        assert new_pid != old_pid
        assert reused_port == port
        reused_pgid = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"python3 -c 'import os; print(os.getpgid({new_pid}))'",
        ).strip()
        assert int(reused_pgid) == new_pid
    finally:
        k8s_manager.cleanup_session_workspace(sandbox_id, session_id)
