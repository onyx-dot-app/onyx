"""Webapp preview behavior against a real Next dev server.

Pins the Next-side contracts the preview fixes depend on, which unit tests
cannot see: the dev-resource origin gate and basePath serving.
"""

from __future__ import annotations

import shlex
from uuid import uuid4

import pytest
from httpx import URL
from kubernetes import client

from onyx.db.enums import SharingScope
from onyx.server.features.build.configs import (
    SANDBOX_NAMESPACE,
)
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.server.features.build.session.models import WebappInfo
from tests.common.craft.payloads import default_llm_config
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
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


def test_private_artifact_and_preview_deny_another_authenticated_user(
    ready_webapp_session: PoolSession,
    pool_api_user: DATestUser,
    k8s_admin_user: DATestUser,
    k8s_client: client.CoreV1Api,
) -> None:
    """Private HTTP bytes stay owner-only after the owner's grant is cached."""
    session_id = ready_webapp_session.session_id
    assert pool_api_user.id != k8s_admin_user.id
    viewer = http_client.get(
        f"{API_SERVER_URL}/me",
        headers=k8s_admin_user.headers,
        cookies=k8s_admin_user.cookies,
        follow_redirects=False,
    )
    assert viewer.status_code == 200
    assert viewer.json()["id"] == k8s_admin_user.id
    BuildSessionManager.set_sharing(pool_api_user, session_id, SharingScope.PRIVATE)
    marker = f"craft-private-owner-{uuid4().hex}\n".encode()
    session_root = f"/workspace/sessions/{session_id}"
    paths = ("outputs/owner-only.txt", "outputs/web/public/owner-only.txt")
    write_script = (
        "from pathlib import Path; import os; "
        "assert os.getuid() == os.getgid() == 1000; "
        f"root = Path({session_root!r}); data = bytes.fromhex({marker.hex()!r}); "
        f"paths = {paths!r}; "
        "[(root / path).parent.mkdir(parents=True, exist_ok=True) for path in paths]; "
        "[(root / path).write_bytes(data) for path in paths]"
    )
    try:
        pod_exec(
            k8s_client,
            ready_webapp_session.pod_name,
            SANDBOX_NAMESPACE,
            f"python3 -c {shlex.quote(write_script)}",
        )
        assert (
            BuildSessionManager.download_artifact(pool_api_user, session_id, paths[0])
            == marker
        )
        base = f"{API_SERVER_URL}/build/sessions/{session_id}"
        info_response = http_client.get(
            f"{base}/webapp-info",
            headers=pool_api_user.headers,
            cookies=pool_api_user.cookies,
            follow_redirects=False,
        )
        assert info_response.status_code == 200
        info = WebappInfo.model_validate(info_response.json())
        assert info.has_webapp is True and info.ready is True
        assert info.sharing_scope == SharingScope.PRIVATE
        assert info.webapp_url is not None
        assert URL(info.webapp_url).path == f"/api/build/sessions/{session_id}/webapp"
        preview = proxy_get(pool_api_user, str(session_id), "owner-only.txt")
        assert preview.status_code == 200
        assert preview.content == marker
        for route in (
            "artifacts/outputs/owner-only.txt",
            "webapp-info",
            "webapp/owner-only.txt",
        ):
            denial = http_client.get(
                f"{base}/{route}",
                headers=k8s_admin_user.headers,
                cookies=k8s_admin_user.cookies,
                follow_redirects=False,
            )
            assert denial.status_code == 404, f"{route} returned {denial.status_code}"
            assert marker not in denial.content, route
        assert (
            BuildSessionManager.download_artifact(pool_api_user, session_id, paths[0])
            == marker
        )
        preview_after_denials = proxy_get(
            pool_api_user, str(session_id), "owner-only.txt"
        )
        assert preview_after_denials.status_code == 200
        assert preview_after_denials.content == marker
    finally:
        try:
            BuildSessionManager.delete_file(pool_api_user, session_id, paths[0])
        finally:
            BuildSessionManager.delete_file(pool_api_user, session_id, paths[1])


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
