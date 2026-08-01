"""Shared helpers for webapp-preview tests.

The proxy contracts these pin (Origin/Sec-Fetch header stripping, basePath
serving) must hold identically on every sandbox backend, so the k8s and
docker suites assert them through this single implementation.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_POLL_INTERVAL_S = 2.0


def wait_for_webapp_ready(
    user: DATestUser, session_id: str, *, timeout_s: float
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
    pytest.fail(f"webapp never became ready within timeout: {info}")


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
