"""Tests for the unified tier_gate middleware."""

from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from onyx.server.settings.models import Tier

MiddlewareHarness = tuple[
    Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]],
    Callable[[Request], Awaitable[Response]],
]


@pytest.fixture
def middleware_harness() -> MiddlewareHarness:
    from ee.onyx.server.middleware.tier_gate import add_tier_gate_middleware

    app = MagicMock()
    logger = MagicMock()
    captured: Any = None

    def capture_middleware(_kind: str) -> Callable[[Any], Any]:
        def decorator(func: Any) -> Any:
            nonlocal captured
            captured = func
            return func

        return decorator

    app.middleware = capture_middleware
    add_tier_gate_middleware(app, logger)

    async def call_next(_req: Request) -> Response:
        response = MagicMock()
        response.status_code = 200
        return response

    return captured, call_next  # ty: ignore[invalid-return-type]


def _make_request(path: str) -> MagicMock:
    request = MagicMock()
    request.url.path = path
    return request


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_community_blocked_from_business_path(
    mock_get_tier: MagicMock, middleware_harness: MiddlewareHarness
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/admin/query-history"), call_next)
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_business_passes_business_path(
    mock_get_tier: MagicMock, middleware_harness: MiddlewareHarness
) -> None:
    mock_get_tier.return_value = Tier.BUSINESS
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/admin/query-history"), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_business_blocked_from_enterprise_path(
    mock_get_tier: MagicMock, middleware_harness: MiddlewareHarness
) -> None:
    mock_get_tier.return_value = Tier.BUSINESS
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/admin/hooks"), call_next)
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_enterprise_passes_enterprise_path(
    mock_get_tier: MagicMock, middleware_harness: MiddlewareHarness
) -> None:
    mock_get_tier.return_value = Tier.ENTERPRISE
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/admin/hooks"), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unmapped_path_passes_through(
    middleware_harness: MiddlewareHarness,
) -> None:
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/chat"), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_allowed_prefix_passes_without_tier_check(
    middleware_harness: MiddlewareHarness,
) -> None:
    # /auth is in LICENSE_ENFORCEMENT_ALLOWED_PREFIXES — must pass even
    # though /admin/enterprise-settings (which would otherwise gate it)
    # has no overlap. Just confirms the allowlist short-circuits.
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/auth/login"), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_scim_under_enterprise_settings_resolves_to_enterprise(
    mock_get_tier: MagicMock, middleware_harness: MiddlewareHarness
) -> None:
    # Regression: /admin/enterprise-settings is BUSINESS, but
    # /admin/enterprise-settings/scim must resolve to ENTERPRISE via
    # longest-prefix match.
    mock_get_tier.return_value = Tier.BUSINESS
    middleware, call_next = middleware_harness
    response = await middleware(
        _make_request("/api/admin/enterprise-settings/scim/token"), call_next
    )
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_path_starting_with_api_but_not_api_slash_not_stripped(
    middleware_harness: MiddlewareHarness,
) -> None:
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/apifoo/bar"), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_402_payload_includes_required_tier(
    mock_get_tier: MagicMock, middleware_harness: MiddlewareHarness
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY
    middleware, call_next = middleware_harness
    response = await middleware(_make_request("/api/admin/hooks"), call_next)
    assert response.status_code == 402
    # Body is set on JSONResponse via `content`, accessible as `.body`.
    import json

    payload = json.loads(bytes(response.body))
    assert payload["required_tier"] == "enterprise"
