from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.client.auth import TokenStorage
from mcp.client.auth.utils import should_use_client_metadata_url
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyHttpUrl

from onyx.db.enums import MCPOAuthProviderMode
from onyx.server.auth_check import PUBLIC_ENDPOINT_SPECS, is_route_in_spec_list
from onyx.server.features.mcp import client_metadata
from onyx.server.features.mcp import oauth as mcp_oauth
from onyx.server.features.mcp.models import MCPServerConnection

TEST_WEB_DOMAIN = "https://onyx.example.com"
METADATA_ROUTE = "/mcp/oauth/client-metadata"


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(client_metadata.router, prefix="/mcp")
    return app


def test_mcp_oauth_client_metadata_document_is_public_and_cacheable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_metadata, "WEB_DOMAIN", f"{TEST_WEB_DOMAIN}/")
    app = _build_test_app()

    response = TestClient(app).get(METADATA_ROUTE)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=3600"
    assert response.json() == {
        "client_id": f"{TEST_WEB_DOMAIN}/api/mcp/oauth/client-metadata",
        "client_name": "Onyx",
        "redirect_uris": [f"{TEST_WEB_DOMAIN}/mcp/oauth/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }

    metadata_route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == METADATA_ROUTE  # ods: ignore[getattr]
    )
    assert is_route_in_spec_list(metadata_route, PUBLIC_ENDPOINT_SPECS)


@pytest.mark.parametrize(
    ("web_domain", "expected_url"),
    [
        (
            "https://onyx.example.com",
            "https://onyx.example.com/api/mcp/oauth/client-metadata",
        ),
        ("http://localhost:3000", None),
    ],
)
def test_mcp_oauth_client_metadata_url_requires_https(
    monkeypatch: pytest.MonkeyPatch,
    web_domain: str,
    expected_url: str | None,
) -> None:
    monkeypatch.setattr(client_metadata, "WEB_DOMAIN", web_domain)

    assert client_metadata.validated_mcp_oauth_client_metadata_url() == expected_url


@pytest.mark.parametrize(
    ("client_id", "expected"),
    [
        ("https://onyx.example.com/api/mcp/oauth/client-metadata", True),
        ("https://old-domain.example.com/api/mcp/oauth/client-metadata", True),
        ("http://onyx.example.com/api/mcp/oauth/client-metadata", False),
        ("mock-client-3f2a9c", False),
        (None, False),
    ],
)
def test_mcp_oauth_cimd_client_id_is_recognized_by_shape(
    client_id: str | None, expected: bool
) -> None:
    assert client_metadata.is_mcp_oauth_cimd_client_id(client_id) is expected


@pytest.mark.parametrize("cimd_enabled", [True, False])
def test_a_server_with_cimd_off_registers_through_dcr(
    monkeypatch: pytest.MonkeyPatch, cimd_enabled: bool
) -> None:
    metadata_url = f"{TEST_WEB_DOMAIN}/api/mcp/oauth/client-metadata"
    monkeypatch.setattr(
        mcp_oauth, "validated_mcp_oauth_client_metadata_url", lambda: metadata_url
    )
    provider = mcp_oauth.make_oauth_provider_with_storage(
        MCPServerConnection(
            id=1,
            name="CIMD server",
            server_url="https://mcp.example.com/mcp",
            transport=None,
            oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
            oauth_cimd_enabled=cimd_enabled,
            oauth_authorization_endpoint=None,
            oauth_token_endpoint=None,
        ),
        MagicMock(spec=TokenStorage),
    )
    advertises_cimd = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.example.com"),
        authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
        client_id_metadata_document_supported=True,
    )

    assert (
        should_use_client_metadata_url(
            advertises_cimd, provider.context.client_metadata_url
        )
        is cimd_enabled
    )
