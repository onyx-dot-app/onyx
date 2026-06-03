from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from mcp.shared.auth import OAuthClientInformationFull

from onyx.auth.oauth_token_manager import build_oauth_authorization_url
from onyx.auth.oauth_token_manager import exchange_oauth_code_for_token
from onyx.db.models import MCPServer as DbMCPServer
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp.api import _mcp_known_provider_flow_params


def _make_mcp_server_stub(
    *,
    auth_endpoint: str | None = "https://accounts.example.com/oauth/authorize",
    token_endpoint: str | None = "https://accounts.example.com/oauth/token",
    scopes: list[str] | None = None,
    params: dict[str, str] | None = None,
) -> DbMCPServer:
    return cast(
        DbMCPServer,
        SimpleNamespace(
            oauth_authorization_endpoint=auth_endpoint,
            oauth_token_endpoint=token_endpoint,
            oauth_scopes_override=scopes,
            oauth_additional_auth_params=params,
            server_url="https://mcp.example.com/mcp",
        ),
    )


def _make_client_info_stub(
    *, client_id: str | None = "client-123", client_secret: str | None = "secret-123"
) -> OAuthClientInformationFull:
    return cast(
        OAuthClientInformationFull,
        SimpleNamespace(client_id=client_id, client_secret=client_secret),
    )


def test_known_provider_flow_params_maps_server_and_client_fields() -> None:
    params = _mcp_known_provider_flow_params(
        _make_mcp_server_stub(
            scopes=["scope.one", "scope.two"], params={"access_type": "offline"}
        ),
        _make_client_info_stub(),
    )
    assert params.authorization_url == "https://accounts.example.com/oauth/authorize"
    assert params.token_url == "https://accounts.example.com/oauth/token"
    assert params.client_id == "client-123"
    assert params.client_secret == "secret-123"
    assert params.scopes == ["scope.one", "scope.two"]
    assert params.additional_params == {"access_type": "offline"}


def test_known_provider_oauth_url_includes_required_and_optional_params() -> None:
    oauth_url = build_oauth_authorization_url(
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(
                scopes=["scope.one", "scope.two"], params={"access_type": "offline"}
            ),
            _make_client_info_stub(),
        ),
        redirect_uri="https://onyx.example.com/mcp/oauth/callback",
        state="state-123",
        code_challenge="challenge-456",
        resource="https://mcp.example.com/mcp",
    )
    query = parse_qs(urlparse(oauth_url).query)
    assert query["client_id"] == ["client-123"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-123"]
    assert query["code_challenge"] == ["challenge-456"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["scope.one scope.two"]
    assert query["resource"] == ["https://mcp.example.com/mcp"]
    assert query["access_type"] == ["offline"]


def test_known_provider_flow_params_requires_endpoints() -> None:
    with pytest.raises(OnyxError, match="oauth_authorization_endpoint"):
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(auth_endpoint=None), _make_client_info_stub()
        )


def test_known_provider_flow_params_requires_client_id() -> None:
    with pytest.raises(OnyxError, match="client_id"):
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(), _make_client_info_stub(client_id=None)
        )


def test_known_provider_code_exchange_sends_code_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, dict[str, str]] = {}

    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, str | int]:
            return {
                "access_token": "token-abc",
                "token_type": "Bearer",
                "refresh_token": "refresh-abc",
                "expires_in": 3600,
            }

    def _fake_post(url: str, data: dict[str, str], **kwargs: object) -> _Response:
        del url, kwargs
        captured["data"] = data
        return _Response()

    monkeypatch.setattr("onyx.auth.oauth_token_manager.requests.post", _fake_post)
    # Placeholder host can't resolve; the SSRF guard is exercised in test_mcp_ssrf.
    monkeypatch.setattr(
        "onyx.auth.oauth_token_manager.validate_oauth_endpoint_url",
        lambda url: None,  # noqa: ARG005
    )

    token_payload = exchange_oauth_code_for_token(
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(), _make_client_info_stub()
        ),
        code="auth-code-123",
        redirect_uri="https://onyx.example.com/mcp/oauth/callback",
        code_verifier="verifier-123",
    )
    assert token_payload["access_token"] == "token-abc"
    assert "expires_at" in token_payload
    assert captured["data"]["code_verifier"] == "verifier-123"
    assert captured["data"]["client_secret"] == "secret-123"
