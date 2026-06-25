"""HTTP wrapper for build-mode approval endpoints.

Modeled on ``BuildSessionManager``: a thin static façade over the approval
HTTP API, using the same ``user.headers`` / ``user.cookies`` auth pattern
used elsewhere in ``common_utils.managers``.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


class BuildApprovalsManager:
    """Static wrapper around the build-mode approval HTTP API."""

    @staticmethod
    def list_live(user: DATestUser, session_id: UUID) -> list[dict[str, Any]]:
        response = client.get(
            f"{API_SERVER_URL}/build/approvals/sessions/{session_id}/live",
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        assert isinstance(items, list)
        return items

    @staticmethod
    def wait_for_pending(
        user: DATestUser, session_id: UUID, timeout_s: float = 30.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            items = BuildApprovalsManager.list_live(user, session_id)
            if items:
                return items[0]
            time.sleep(0.5)
        raise AssertionError(
            f"No pending approval surfaced for session {session_id} within {timeout_s}s."
        )
