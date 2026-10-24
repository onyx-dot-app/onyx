"""Tests for the unified tier_gate middleware."""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from starlette.responses import Response

from onyx.server.settings.models import Tier


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from ee.onyx.server.middleware.tier_gate import tier_gate_middleware

    app = tier_gate_middleware(Response(status_code=200), MagicMock())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_community_blocked_from_business_path(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY

    response = await client.get("/api/admin/query-history")
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("onyx.server.middleware.api_prefix.APP_API_PREFIX", "v2")
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_custom_api_prefix_still_applies_tier_gate(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY

    response = await client.get("/v2/admin/hooks")
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_bare_path_still_applies_tier_gate(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY

    response = await client.get("/admin/query-history")
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_business_passes_business_path(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.BUSINESS

    response = await client.get("/api/admin/query-history")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_community_blocked_from_gateway(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY

    response = await client.get("/api/gateway/v1/models")

    assert response.status_code == 402
    assert response.json()["required_tier"] == "business"


@pytest.mark.asyncio
@pytest.mark.parametrize("current_tier", [Tier.BUSINESS, Tier.ENTERPRISE])
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_paid_tiers_pass_gateway(
    mock_get_tier: MagicMock,
    current_tier: Tier,
    client: httpx.AsyncClient,
) -> None:
    mock_get_tier.return_value = current_tier

    response = await client.get("/api/gateway/v1/models")

    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_business_blocked_from_enterprise_path(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.BUSINESS

    response = await client.get("/api/admin/hooks")
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_enterprise_passes_enterprise_path(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.ENTERPRISE

    response = await client.get("/api/admin/hooks")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_business_blocked_from_log_export(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.BUSINESS

    response = await client.get("/api/admin/log-export")
    assert response.status_code == 402


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_enterprise_passes_log_export(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.ENTERPRISE

    response = await client.get("/api/admin/log-export")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unmapped_path_passes_through(
    client: httpx.AsyncClient,
) -> None:

    response = await client.get("/api/chat")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_allowed_prefix_passes_without_tier_check(
    client: httpx.AsyncClient,
) -> None:
    # /auth is in LICENSE_ENFORCEMENT_ALLOWED_PREFIXES — must pass even
    # though /admin/enterprise-settings (which would otherwise gate it)
    # has no overlap. Just confirms the allowlist short-circuits.

    response = await client.get("/api/auth/login")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_scim_under_enterprise_settings_resolves_to_enterprise(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    # Regression: /admin/enterprise-settings is BUSINESS, but
    # /admin/enterprise-settings/scim must resolve to ENTERPRISE via
    # longest-prefix match.
    mock_get_tier.return_value = Tier.BUSINESS

    response = await client.get("/api/admin/enterprise-settings/scim/token")
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_path_starting_with_api_but_not_api_slash_not_stripped(
    client: httpx.AsyncClient,
) -> None:

    response = await client.get("/apifoo/bar")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_402_payload_includes_required_tier(
    mock_get_tier: MagicMock, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.COMMUNITY

    response = await client.get("/api/admin/hooks")
    assert response.status_code == 402
    # Body is set on JSONResponse via `content`, accessible as `.body`.
    payload = response.json()
    assert payload["required_tier"] == "enterprise"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/scim/v2/ServiceProviderConfig",
        "/scim/v2/ResourceTypes",
        "/scim/v2/Schemas",
    ],
)
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_scim_discovery_passes_without_tier_check(
    mock_get_tier: MagicMock, path: str, client: httpx.AsyncClient
) -> None:

    response = await client.get(path)
    assert response.status_code == 200
    mock_get_tier.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/scim/v2/Users", "/scim/v2/Groups"])
@patch("ee.onyx.server.middleware.tier_gate.get_tier")
async def test_business_blocked_from_scim_resources(
    mock_get_tier: MagicMock, path: str, client: httpx.AsyncClient
) -> None:
    mock_get_tier.return_value = Tier.BUSINESS

    response = await client.get(path)
    assert response.status_code == 402
