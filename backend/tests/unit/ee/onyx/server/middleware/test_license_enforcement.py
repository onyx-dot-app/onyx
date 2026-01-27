"""Tests for license enforcement middleware."""

from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from ee.onyx.server.middleware.license_enforcement import _is_ee_only_path
from ee.onyx.server.middleware.license_enforcement import _is_path_allowed
from onyx.server.settings.models import ApplicationStatus

# Type alias for the middleware harness tuple
MiddlewareHarness = tuple[
    Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]],
    Callable[[Request], Awaitable[Response]],
]


class TestPathAllowlist:
    """Tests for the path allowlist logic."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Each allowlisted prefix (one example each)
            ("/auth", True),
            ("/license", True),
            ("/health", True),
            ("/me", True),
            ("/settings", True),
            ("/enterprise-settings", True),
            ("/tenants/billing-information", True),
            ("/tenants/create-customer-portal-session", True),
            # Verify prefix matching works (subpath of allowlisted)
            ("/auth/callback/google", True),
            # Blocked paths (core functionality that requires license)
            ("/chat", False),
            ("/search", False),
            ("/admin", False),
            ("/connector", False),
            ("/persona", False),
        ],
    )
    def test_path_allowlist(self, path: str, expected: bool) -> None:
        """Verify correct paths are allowed/blocked when license is gated."""
        assert _is_path_allowed(path) is expected


class TestEEOnlyPaths:
    """Tests for EE-only path detection."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # EE-only paths
            ("/manage/admin/user-group", True),
            ("/analytics", True),
            ("/admin/chat-sessions", True),
            ("/admin/query-history", True),
            ("/admin/usage-report", True),
            ("/manage/admin/standard-answer", True),
            ("/admin/token-rate-limits", True),
            ("/evals", True),
            # Non-EE paths (community features)
            ("/chat", False),
            ("/search", False),
            ("/connector", False),
            ("/persona", False),
        ],
    )
    def test_ee_only_paths(self, path: str, expected: bool) -> None:
        """Verify EE-only paths are correctly identified."""
        assert _is_ee_only_path(path) is expected


class TestLicenseEnforcementMiddleware:
    """Tests for middleware behavior under different conditions."""

    @pytest.fixture
    def middleware_harness(self) -> MiddlewareHarness:
        """Create a test harness for the middleware."""
        from ee.onyx.server.middleware.license_enforcement import (
            add_license_enforcement_middleware,
        )

        app = MagicMock()
        logger = MagicMock()
        captured_middleware: Any = None

        def capture_middleware(middleware_type: str) -> Callable[[Any], Any]:
            def decorator(func: Any) -> Any:
                nonlocal captured_middleware
                captured_middleware = func
                return func

            return decorator

        app.middleware = capture_middleware
        add_license_enforcement_middleware(app, logger)

        async def call_next(req: Request) -> Response:
            response = MagicMock()
            response.status_code = 200
            return response

        return captured_middleware, call_next

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_gated_access_status_gets_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """GATED_ACCESS status blocks non-allowlisted paths with 402."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GATED_ACCESS
        mock_get_metadata.return_value = mock_metadata

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 402

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_grace_period_allows_access(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """GRACE_PERIOD status allows access (for notifications only, not blocking)."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GRACE_PERIOD
        mock_metadata.used_seats = 5
        mock_metadata.seats = 10
        mock_get_metadata.return_value = mock_metadata

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch(
        "ee.onyx.server.middleware.license_enforcement.get_session_with_current_tenant"
    )
    @patch("ee.onyx.server.middleware.license_enforcement.refresh_license_cache")
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_no_license_blocks_ee_only_paths(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        mock_refresh: MagicMock,
        mock_get_session: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """No license blocks EE-only paths with 402."""
        mock_get_tenant.return_value = "default"
        mock_get_metadata.return_value = None
        mock_refresh.return_value = None  # Still no license after DB check

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/analytics"  # EE-only path

        response = await middleware(mock_request, call_next)
        assert response.status_code == 402

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
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
        mock_get_session: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """No license allows community features (non-EE paths)."""
        mock_get_tenant.return_value = "default"
        mock_get_metadata.return_value = None
        mock_refresh.return_value = None  # Still no license after DB check

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"  # Community path

        response = await middleware(mock_request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_redis_error_fails_open(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """Redis errors should not block users - fail open to allow access."""
        from redis.exceptions import RedisError

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.side_effect = RedisError("Connection failed")

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 200  # Fail open

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        False,
    )
    async def test_disabled_enforcement_allows_all(
        self,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """When enforcement is disabled, all requests pass through."""
        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_seat_limit_exceeded_gets_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """Seat limit exceeded returns 402."""
        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_metadata.used_seats = 15
        mock_metadata.seats = 10  # Over limit
        mock_get_metadata.return_value = mock_metadata

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 402
