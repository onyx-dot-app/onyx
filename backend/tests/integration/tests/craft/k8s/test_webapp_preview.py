"""Webapp preview behavior against a real Next dev server.

Pins the Next-side contracts the preview fixes depend on, which unit tests
cannot see: the dev-resource origin gate and basePath serving.
"""

from __future__ import annotations

import pytest

from onyx.server.features.build.configs import SANDBOX_BACKEND, SandboxBackend
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import PoolSession
from tests.integration.tests.craft.webapp_preview import (
    proxy_get,
    wait_for_webapp_ready,
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

_WEBAPP_READY_TIMEOUT_S = 120.0


def test_preview_serves_at_base_path_and_reports_ready(
    pool_session: PoolSession,
    pool_api_user: DATestUser,
) -> None:
    """``ready`` flips true and the route users actually load returns 200."""
    session_id = str(pool_session.session_id)
    wait_for_webapp_ready(pool_api_user, session_id, timeout_s=_WEBAPP_READY_TIMEOUT_S)

    resp = proxy_get(pool_api_user, session_id)
    assert resp.status_code == 200, resp.text[:500]


def test_dev_resources_not_blocked_by_origin_gate(
    pool_session: PoolSession,
    pool_api_user: DATestUser,
) -> None:
    """A browser-shaped dev-resource request must not hit Next's cross-origin
    403 (``blockCrossSiteDEV`` rejects /_next/* when the Origin hostname is
    not allowlisted — the exact failure from the 2026-07-06 incident)."""
    session_id = str(pool_session.session_id)
    wait_for_webapp_ready(pool_api_user, session_id, timeout_s=_WEBAPP_READY_TIMEOUT_S)

    resp = proxy_get(
        pool_api_user, session_id, "_next/static/onyx-origin-gate-probe.js"
    )
    # 404 for a nonexistent asset is fine; the gate rejects before routing,
    # so a 403 means Origin/sec-fetch-* leaked through the proxy or the
    # allowlist regressed on a Next upgrade.
    assert resp.status_code != 403, resp.text[:500]
