"""Webapp preview behavior against a real Next dev server.

Pins the Next-side contracts the preview fixes depend on, which unit tests
cannot see: the dev-resource origin gate and basePath serving.
"""

from __future__ import annotations

import time

import httpx
import pytest

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s.k8s_fixtures import PoolSession

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)

_WEBAPP_READY_TIMEOUT_S = 120.0
_POLL_INTERVAL_S = 2.0


def _wait_for_webapp_ready(user: DATestUser, session_id: str) -> None:
    deadline = time.monotonic() + _WEBAPP_READY_TIMEOUT_S
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
    pytest.fail(f"webapp never became ready within timeout: {info}")


def _proxy_get(user: DATestUser, session_id: str, path: str = "") -> httpx.Response:
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


def test_preview_serves_at_base_path_and_reports_ready(
    pool_session: PoolSession,
    pool_api_user: DATestUser,
) -> None:
    """``ready`` flips true and the route users actually load returns 200."""
    session_id = str(pool_session.session_id)
    _wait_for_webapp_ready(pool_api_user, session_id)

    resp = _proxy_get(pool_api_user, session_id)
    assert resp.status_code == 200, resp.text[:500]


def test_dev_resources_not_blocked_by_origin_gate(
    pool_session: PoolSession,
    pool_api_user: DATestUser,
) -> None:
    """A browser-shaped dev-resource request must not hit Next's cross-origin
    403 (``blockCrossSiteDEV`` rejects /_next/* when the Origin hostname is
    not allowlisted — the exact failure from the 2026-07-06 incident)."""
    session_id = str(pool_session.session_id)
    _wait_for_webapp_ready(pool_api_user, session_id)

    resp = _proxy_get(
        pool_api_user, session_id, "_next/static/onyx-origin-gate-probe.js"
    )
    # 404 for a nonexistent asset is fine; the gate rejects before routing,
    # so a 403 means Origin/sec-fetch-* leaked through the proxy or the
    # allowlist regressed on a Next upgrade.
    assert resp.status_code != 403, resp.text[:500]
