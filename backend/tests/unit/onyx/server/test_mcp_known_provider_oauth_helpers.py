from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from mcp.shared.auth import OAuthClientInformationFull

from onyx.db.models import MCPServer as DbMCPServer
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.errors import TokenRefreshTerminalError
from onyx.oauth.errors import TokenRefreshTransientError
from onyx.oauth.exchange import build_oauth_authorization_url
from onyx.oauth.exchange import exchange_oauth_code_for_token
from onyx.oauth.exchange import exchange_refresh_token
from onyx.oauth.exchange import OAuthFlowParams
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

    monkeypatch.setattr("onyx.oauth.exchange.requests.post", _fake_post)
    # Placeholder host can't resolve; the SSRF guard is exercised in test_mcp_ssrf.
    monkeypatch.setattr(
        "onyx.oauth.exchange.validate_oauth_endpoint_url",
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


def _patch_refresh_post(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, object], *, status: int = 200
) -> dict[str, dict[str, str]]:
    captured: dict[str, dict[str, str]] = {}

    class _Response:
        status_code = status

        @staticmethod
        def json() -> dict[str, object]:
            return body

    def _fake_post(url: str, data: dict[str, str], **kwargs: object) -> _Response:
        del url, kwargs
        captured["data"] = data
        return _Response()

    monkeypatch.setattr("onyx.oauth.exchange.requests.post", _fake_post)
    monkeypatch.setattr(
        "onyx.oauth.exchange.validate_oauth_endpoint_url",
        lambda url: None,  # noqa: ARG005
    )
    return captured


def _refresh_params() -> OAuthFlowParams:
    return _mcp_known_provider_flow_params(
        _make_mcp_server_stub(), _make_client_info_stub()
    )


def test_exchange_refresh_token_computes_expiry_and_sends_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_refresh_post(
        monkeypatch,
        {"access_token": "fresh", "token_type": "Bearer", "expires_in": 3600},
    )
    result = exchange_refresh_token(_refresh_params(), "refresh-old")
    assert result["access_token"] == "fresh"
    assert "expires_at" in result  # computed from expires_in
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "refresh-old"
    assert captured["data"]["client_secret"] == "secret-123"


def test_exchange_refresh_token_preserves_refresh_token_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_refresh_post(monkeypatch, {"access_token": "fresh", "token_type": "Bearer"})
    # Provider didn't rotate the refresh token → carry the incoming one forward.
    assert (
        exchange_refresh_token(_refresh_params(), "refresh-old")["refresh_token"]
        == "refresh-old"
    )


def test_exchange_refresh_token_uses_rotated_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_refresh_post(
        monkeypatch,
        {"access_token": "fresh", "token_type": "Bearer", "refresh_token": "rotated"},
    )
    assert (
        exchange_refresh_token(_refresh_params(), "refresh-old")["refresh_token"]
        == "rotated"
    )


def test_exchange_refresh_token_dead_grant_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_refresh_post(monkeypatch, {"error": "invalid_grant"}, status=400)
    with pytest.raises(TokenRefreshTerminalError):
        exchange_refresh_token(_refresh_params(), "refresh-old")


def test_exchange_refresh_token_other_4xx_is_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # invalid_client is a misconfig, not a dead grant — reconnecting wouldn't fix it.
    _patch_refresh_post(monkeypatch, {"error": "invalid_client"}, status=400)
    with pytest.raises(TokenRefreshTransientError):
        exchange_refresh_token(_refresh_params(), "refresh-old")
