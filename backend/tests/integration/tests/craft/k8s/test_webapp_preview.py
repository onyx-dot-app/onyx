"""Webapp preview behavior against a real Next dev server.

Pins the Next-side contracts the preview fixes depend on, which unit tests
cannot see: the dev-resource origin gate and basePath serving.
"""

from __future__ import annotations

import pytest
from kubernetes import client

from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_NAMESPACE,
    SandboxBackend,
)
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
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
        reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
    ),
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

    The docker suite pins the same bytes; both matter because the two managers
    write the script separately. Mode 444 is what keeps a stray redirect from
    clobbering the one file opencode's deny rules treat as fixed.
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
