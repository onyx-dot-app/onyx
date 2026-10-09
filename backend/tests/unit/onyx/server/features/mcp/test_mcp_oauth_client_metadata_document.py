import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.server.auth_check import PUBLIC_ENDPOINT_SPECS, is_route_in_spec_list
from onyx.server.features.mcp import client_metadata

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
