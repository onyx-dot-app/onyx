from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest

from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.feishu import connector as feishu_connector_module
from onyx.connectors.feishu.connector import FeishuConnector


class _MockResponse:
    def __init__(self, payload: dict[str, Any], text: str = "") -> None:
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._payload


def test_oauth_authorization_url_uses_feishu_config() -> None:
    with patch.object(feishu_connector_module, "FEISHU_CLIENT_ID", "cli_123"):
        with patch.object(
            feishu_connector_module, "FEISHU_OAUTH_SCOPE", "scope.one scope.two"
        ):
            with patch.object(feishu_connector_module, "FEISHU_REDIRECT_URI", None):
                url = FeishuConnector.oauth_authorization_url(
                    base_domain="https://onyx.example.com",
                    state="state-123",
                    additional_kwargs={},
                )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.feishu.cn"
    assert parsed.path == "/open-apis/authen/v1/authorize"
    assert query["client_id"] == ["cli_123"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["scope.one scope.two"]
    assert query["state"] == ["state-123"]
    assert query["redirect_uri"] == [
        "https://onyx.example.com/connector/oauth/callback/feishu"
    ]


def test_oauth_code_to_token_unwraps_nested_feishu_payloads() -> None:
    responses = [
        _MockResponse(
            {
                "data": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                }
            },
            text="token-response",
        ),
        _MockResponse(
            {
                "data": {
                    "open_id": "ou_123",
                    "union_id": "on_456",
                    "name": "Feishu User",
                    "email": "user@example.com",
                    "avatar_url": "https://img.example.com/avatar.png",
                }
            }
        ),
    ]

    with patch.object(feishu_connector_module, "FEISHU_CLIENT_ID", "cli_123"):
        with patch.object(feishu_connector_module, "FEISHU_CLIENT_SECRET", "sec_123"):
            with patch.object(feishu_connector_module, "FEISHU_REDIRECT_URI", None):
                with patch(
                    "onyx.connectors.feishu.connector.request_with_retries",
                    side_effect=responses,
                ) as mock_request:
                    token = FeishuConnector.oauth_code_to_token(
                        base_domain="https://onyx.example.com",
                        code="oauth-code",
                        additional_kwargs={},
                    )

    assert token["access_token"] == "access-token"
    assert token["refresh_token"] == "refresh-token"
    assert token["open_id"] == "ou_123"
    assert token["email"] == "user@example.com"
    assert token["user_info"]["name"] == "Feishu User"
    assert mock_request.call_count == 2




def test_oauth_code_to_token_generates_fallback_email() -> None:
    responses = [
        _MockResponse(
            {
                "data": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                }
            }
        ),
        _MockResponse(
            {
                "data": {
                    "open_id": "ou_123",
                    "union_id": "on_456",
                    "name": "Feishu User",
                }
            }
        ),
    ]

    with patch.object(feishu_connector_module, "FEISHU_CLIENT_ID", "cli_123"):
        with patch.object(feishu_connector_module, "FEISHU_CLIENT_SECRET", "sec_123"):
            with patch.object(feishu_connector_module, "FEISHU_REDIRECT_URI", None):
                with patch.object(
                    feishu_connector_module, "FEISHU_OAUTH_EMAIL_FALLBACK", True
                ):
                    with patch(
                        "onyx.connectors.feishu.connector.request_with_retries",
                        side_effect=responses,
                    ):
                        token = FeishuConnector.oauth_code_to_token(
                            base_domain="https://onyx.example.com",
                            code="oauth-code",
                            additional_kwargs={},
                        )

    assert token["email"] == "feishu@ou_123.local"
def test_oauth_code_to_token_raises_on_feishu_application_error() -> None:
    responses = [
        _MockResponse(
            {
                "data": {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                }
            }
        ),
        _MockResponse({"code": 99991663, "msg": "user access token is invalid"}),
    ]

    with patch.object(feishu_connector_module, "FEISHU_CLIENT_ID", "cli_123"):
        with patch.object(feishu_connector_module, "FEISHU_CLIENT_SECRET", "sec_123"):
            with patch.object(feishu_connector_module, "FEISHU_REDIRECT_URI", None):
                with patch(
                    "onyx.connectors.feishu.connector.request_with_retries",
                    side_effect=responses,
                ):
                    with pytest.raises(RuntimeError, match="Feishu API request failed"):
                        FeishuConnector.oauth_code_to_token(
                            base_domain="https://onyx.example.com",
                            code="oauth-code",
                            additional_kwargs={},
                        )


def test_load_credentials_requires_access_token() -> None:
    connector = FeishuConnector()

    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})


def test_validate_connector_settings_refreshes_user_info() -> None:
    connector = FeishuConnector()
    connector.load_credentials({"access_token": "access-token"})

    with patch(
        "onyx.connectors.feishu.connector.request_with_retries",
        return_value=_MockResponse(
            {"data": {"open_id": "ou_123", "name": "Feishu User"}}
        ),
    ):
        connector.validate_connector_settings()

    assert connector.user_info == {"open_id": "ou_123", "name": "Feishu User"}


def test_validate_connector_settings_raises_on_feishu_application_error() -> None:
    connector = FeishuConnector()
    connector.load_credentials({"access_token": "access-token"})

    with patch(
        "onyx.connectors.feishu.connector.request_with_retries",
        return_value=_MockResponse(
            {"code": 99991663, "msg": "user access token is invalid"}
        ),
    ):
        with pytest.raises(RuntimeError, match="Feishu API request failed"):
            connector.validate_connector_settings()

