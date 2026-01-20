"""Tests for license enforcement middleware."""

import json
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from ee.onyx.server.middleware.license_enforcement import _is_path_allowed

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
            # User management paths (for resolving seat limit issues)
            ("/manage/users", True),
            ("/manage/users/accepted", True),
            ("/manage/admin/users", True),
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
    @patch("ee.onyx.server.middleware.license_enforcement.MULTI_TENANT", True)
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.is_tenant_gated")
    async def test_gated_tenant_gets_402(
        self,
        mock_is_gated: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """Gated tenants receive 402 Payment Required on non-allowlisted paths."""
        mock_get_tenant.return_value = "gated_tenant"
        mock_is_gated.return_value = True

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
    @patch("ee.onyx.server.middleware.license_enforcement.MULTI_TENANT", False)
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_no_license_self_hosted_gets_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """Self-hosted with no license receives 402 on non-allowlisted paths."""
        mock_get_tenant.return_value = "default"
        mock_get_metadata.return_value = None

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
    @patch("ee.onyx.server.middleware.license_enforcement.MULTI_TENANT", True)
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.is_tenant_gated")
    async def test_redis_error_fails_open(
        self,
        mock_is_gated: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """Redis errors should not block users - fail open to allow access."""
        from redis.exceptions import RedisError

        mock_get_tenant.return_value = "test_tenant"
        mock_is_gated.side_effect = RedisError("Connection failed")

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 200  # Fail open

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.server.middleware.license_enforcement.MULTI_TENANT", False)
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_used_seats")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_seat_limit_exceeded_gets_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_used_seats: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """When used seats exceed licensed seats, return 402 with seat_limit_exceeded."""
        from onyx.server.settings.models import ApplicationStatus

        mock_get_tenant.return_value = "test_tenant"

        # Create mock metadata with 5 licensed seats
        mock_metadata = MagicMock()
        mock_metadata.seats = 5
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_get_metadata.return_value = mock_metadata

        # But 10 seats are in use
        mock_get_used_seats.return_value = 10

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 402
        # Verify it's specifically seat_limit_exceeded, not license_expired
        body = json.loads(bytes(response.body).decode())
        assert body["detail"]["error"] == "seat_limit_exceeded"

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.middleware.license_enforcement.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.server.middleware.license_enforcement.MULTI_TENANT", False)
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_used_seats")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    async def test_within_seat_limit_passes(
        self,
        mock_get_metadata: MagicMock,
        mock_get_used_seats: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """When used seats are within license limit, request proceeds."""
        from onyx.server.settings.models import ApplicationStatus

        mock_get_tenant.return_value = "test_tenant"

        # 10 licensed seats
        mock_metadata = MagicMock()
        mock_metadata.seats = 10
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_get_metadata.return_value = mock_metadata

        # Only 5 in use
        mock_get_used_seats.return_value = 5

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
    @patch("ee.onyx.server.middleware.license_enforcement.MULTI_TENANT", True)
    @patch("ee.onyx.server.middleware.license_enforcement.get_current_tenant_id")
    @patch("ee.onyx.server.middleware.license_enforcement.get_used_seats")
    @patch("ee.onyx.server.middleware.license_enforcement.get_cached_license_metadata")
    @patch("ee.onyx.server.middleware.license_enforcement.is_tenant_gated")
    async def test_seat_limit_enforced_for_multi_tenant(
        self,
        mock_is_gated: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_used_seats: MagicMock,
        mock_get_tenant: MagicMock,
        middleware_harness: MiddlewareHarness,
    ) -> None:
        """Seat limit enforcement works for multi-tenant deployments too."""
        from onyx.server.settings.models import ApplicationStatus

        mock_get_tenant.return_value = "cloud_tenant"
        mock_is_gated.return_value = False  # Not gated by subscription

        # 5 licensed seats
        mock_metadata = MagicMock()
        mock_metadata.seats = 5
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_get_metadata.return_value = mock_metadata

        # But 8 in use
        mock_get_used_seats.return_value = 8

        middleware, call_next = middleware_harness
        mock_request = MagicMock()
        mock_request.url.path = "/api/chat"

        response = await middleware(mock_request, call_next)
        assert response.status_code == 402
        body = json.loads(bytes(response.body).decode())
        assert body["detail"]["error"] == "seat_limit_exceeded"
