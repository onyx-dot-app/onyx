"""Tests for license enforcement middleware."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from starlette.responses import Response

from ee.onyx.configs.license_enforcement_config import (
    LICENSE_ENFORCEMENT_ALLOWED_PREFIXES,
)
from ee.onyx.server.middleware.license_enforcement import _is_path_allowed
from onyx.server.middleware import api_prefix
from onyx.server.settings.models import ApplicationStatus

# Paths that should be blocked (core functionality requiring license)
BLOCKED_PATHS = [
    "/chat",
    "/search",
    "/admin/connectors",
    "/connector",
    "/persona",
]


class TestPathAllowlist:
    """Tests for the path allowlist logic.

    Uses LICENSE_ENFORCEMENT_ALLOWED_PREFIXES from the constants module
    as the source of truth to ensure tests stay in sync with production code.
    """

    # Sorted so the parametrization order is deterministic across pytest-xdist
    # workers; iterating the frozenset directly varies with per-process hash
    # randomization, which makes xdist abort on a collection mismatch.
    @pytest.mark.parametrize("path", sorted(LICENSE_ENFORCEMENT_ALLOWED_PREFIXES))
    def test_allowed_paths_are_allowed(self, path: str) -> None:
        """All paths in LICENSE_ENFORCEMENT_ALLOWED_PREFIXES should be allowed."""
        assert _is_path_allowed(path) is True

    def test_allowed_path_prefix_matching(self) -> None:
        """Subpaths of allowed prefixes should also be allowed."""
        assert _is_path_allowed("/auth/callback/google") is True
        assert _is_path_allowed("/admin/billing/checkout") is True
        assert _is_path_allowed("/mcp/oauth/client-metadata") is True

    def test_custom_api_prefix_allowlist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(api_prefix, "APP_API_PREFIX", "v2")
        assert _is_path_allowed(api_prefix.strip_api_prefix("/v2/auth/login")) is True
        assert (
            _is_path_allowed(api_prefix.strip_api_prefix("/v2/admin/billing/checkout"))
            is True
        )

    @pytest.mark.parametrize("path", BLOCKED_PATHS)
    def test_blocked_paths_are_blocked(self, path: str) -> None:
        """Core functionality paths should be blocked when license is gated."""
        assert _is_path_allowed(path) is False


class TestLicenseEnforcementMiddleware:
    """Tests for middleware behavior under different conditions."""

    @pytest_asyncio.fixture
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        from ee.onyx.server.middleware.license_enforcement import (
            license_enforcement_middleware,
        )

        app = license_enforcement_middleware(Response(status_code=200), MagicMock())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    @pytest.mark.asyncio
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_gated_access_status_gets_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """GATED_ACCESS status blocks non-allowlisted paths with 402."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GATED_ACCESS
        mock_metadata.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        mock_get_metadata.return_value = mock_metadata

        path = "/api/chat"

        response = await client.get(path)
        assert response.status_code == 402

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.maybe_schedule_license_reclaim"
    )
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_reclaim_is_scheduled_before_gating(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        mock_schedule_reclaim: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """A gated request still triggers the reclaim so the instance can heal."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GATED_ACCESS
        mock_get_metadata.return_value = mock_metadata

        path = "/api/chat"

        response = await client.get(path)

        assert response.status_code == 402
        mock_schedule_reclaim.assert_called_once_with(
            mock_metadata.expires_at, "default"
        )

    @pytest.mark.asyncio
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_grace_period_allows_access(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """GRACE_PERIOD status allows access (for notifications only, not blocking)."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GRACE_PERIOD
        mock_metadata.used_seats = 5
        mock_metadata.seats = 10
        mock_metadata.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        mock_get_metadata.return_value = mock_metadata

        path = "/api/chat"

        response = await client.get(path)
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.get_session_with_current_tenant"
    )
    @patch("ee.onyx.server.middleware.license_enforcement.refresh_license_cache")
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_no_license_allows_community_paths(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        mock_refresh: MagicMock,
        mock_get_session: MagicMock,  # noqa: ARG002
        client: httpx.AsyncClient,
    ) -> None:
        """No license allows community features (non-EE paths)."""
        mock_get_tenant.return_value = "default"
        mock_get_metadata.return_value = None
        mock_refresh.return_value = None  # Still no license after DB check

        path = "/api/chat"  # Community path

        response = await client.get(path)
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_redis_error_fails_open(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """Redis errors should not block users - fail open to allow access."""
        from redis.exceptions import RedisError

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.side_effect = RedisError("Connection failed")

        path = "/api/chat"

        response = await client.get(path)
        assert response.status_code == 200  # Fail open

    @pytest.mark.asyncio
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_seat_limit_exceeded_gets_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        client: httpx.AsyncClient,
    ) -> None:
        """Seat limit exceeded returns 402."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_metadata.used_seats = 15
        mock_metadata.seats = 10  # Over limit
        mock_metadata.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        mock_get_metadata.return_value = mock_metadata

        path = "/api/chat"

        response = await client.get(path)
        assert response.status_code == 402
