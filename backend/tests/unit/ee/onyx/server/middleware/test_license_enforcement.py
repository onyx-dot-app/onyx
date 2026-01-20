"""Tests for license enforcement middleware."""

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
