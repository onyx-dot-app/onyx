"""Unit tests for LinearConnector OAuth token refresh logic."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.models import ConnectorMissingCredentialError

_FRESH_ACCESS_TOKEN = "fresh-access-token"
_OLD_ACCESS_TOKEN = "old-access-token"
_REFRESH_TOKEN_VALUE = "refresh-token-value"
_NEW_REFRESH_TOKEN_VALUE = "new-refresh-token-value"
_EXPIRES_IN_SECONDS = 3600


def _make_mock_response(
    ok: bool = True, json_data: dict[str, Any] | None = None, text: str = ""
) -> MagicMock:
    response = MagicMock()
    response.ok = ok
    response.json.return_value = json_data or {}
    response.text = text
    return response


def _refresh_response_payload(
    access_token: str = _FRESH_ACCESS_TOKEN,
    refresh_token: str = _NEW_REFRESH_TOKEN_VALUE,
    expires_in: int = _EXPIRES_IN_SECONDS,
) -> dict[str, Any]:
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }


@patch("onyx.connectors.linear.connector.request_with_retries")
def test_refresh_token_returns_new_credentials(
    mock_request: MagicMock,
) -> None:
    """refresh_token should call the token endpoint and return the new credentials."""
    mock_request.return_value = _make_mock_response(
        ok=True, json_data=_refresh_response_payload()
    )
    connector = LinearConnector()

    before = time.time()
    new_credentials = connector.refresh_token({"refresh_token": _REFRESH_TOKEN_VALUE})
    after = time.time()

    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert new_credentials["refresh_token"] == _NEW_REFRESH_TOKEN_VALUE
    assert int(before + _EXPIRES_IN_SECONDS) <= new_credentials["expire_at"]
    assert new_credentials["expire_at"] <= int(after + _EXPIRES_IN_SECONDS)

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args.kwargs
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"] == "https://api.linear.app/oauth/token"
    assert call_kwargs["data"]["grant_type"] == "refresh_token"
    assert call_kwargs["data"]["refresh_token"] == _REFRESH_TOKEN_VALUE


@patch("onyx.connectors.linear.connector.request_with_retries")
def test_refresh_token_keeps_existing_refresh_token_when_omitted(
    mock_request: MagicMock,
) -> None:
    """Per RFC 6749 §6, refresh responses MAY omit refresh_token; the existing
    one should be preserved instead of raising."""
    mock_request.return_value = _make_mock_response(
        ok=True,
        json_data={
            "access_token": _FRESH_ACCESS_TOKEN,
            "expires_in": _EXPIRES_IN_SECONDS,
        },
    )
    connector = LinearConnector()

    new_credentials = connector.refresh_token({"refresh_token": _REFRESH_TOKEN_VALUE})

    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert new_credentials["refresh_token"] == _REFRESH_TOKEN_VALUE


def test_refresh_token_missing_refresh_token_raises() -> None:
    """refresh_token should raise if no refresh_token is present in credentials."""
    connector = LinearConnector()

    with pytest.raises(ConnectorMissingCredentialError):
        connector.refresh_token({"access_token": _OLD_ACCESS_TOKEN})


@patch("onyx.connectors.linear.connector.request_with_retries")
def test_refresh_token_non_ok_response_raises(mock_request: MagicMock) -> None:
    """refresh_token should raise RuntimeError if the token endpoint returns a non-OK response."""
    mock_request.return_value = _make_mock_response(ok=False, text="invalid_grant")
    connector = LinearConnector()

    with pytest.raises(RuntimeError, match="Failed to refresh token"):
        connector.refresh_token({"refresh_token": _REFRESH_TOKEN_VALUE})


def test_load_credentials_with_api_key_does_not_refresh() -> None:
    """linear_api_key creds should be used directly with no token refresh."""
    connector = LinearConnector()

    new_credentials = connector.load_credentials({"linear_api_key": "api-key-value"})

    assert new_credentials is None
    assert connector.linear_api_key == "api-key-value"


def test_load_credentials_with_access_token_and_no_expiry_does_not_refresh() -> None:
    """Legacy creds without expire_at should be used as a Bearer token without refresh."""
    connector = LinearConnector()

    new_credentials = connector.load_credentials({"access_token": _OLD_ACCESS_TOKEN})

    assert new_credentials is None
    assert connector.linear_api_key == f"Bearer {_OLD_ACCESS_TOKEN}"


@patch("onyx.connectors.linear.connector.request_with_retries")
def test_load_credentials_with_valid_token_does_not_refresh(
    mock_request: MagicMock,
) -> None:
    """Tokens with > 5 minutes left should be used directly without refresh."""
    connector = LinearConnector()

    new_credentials = connector.load_credentials(
        {
            "access_token": _OLD_ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) + _EXPIRES_IN_SECONDS,
        }
    )

    assert new_credentials is None
    assert connector.linear_api_key == f"Bearer {_OLD_ACCESS_TOKEN}"
    mock_request.assert_not_called()


@patch("onyx.connectors.linear.connector.request_with_retries")
def test_load_credentials_with_expired_token_refreshes(
    mock_request: MagicMock,
) -> None:
    """Tokens that have already expired should trigger a refresh."""
    mock_request.return_value = _make_mock_response(
        ok=True, json_data=_refresh_response_payload()
    )
    connector = LinearConnector()

    new_credentials = connector.load_credentials(
        {
            "access_token": _OLD_ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) - 10,
        }
    )

    assert new_credentials is not None
    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert new_credentials["refresh_token"] == _NEW_REFRESH_TOKEN_VALUE
    assert connector.linear_api_key == f"Bearer {_FRESH_ACCESS_TOKEN}"
    mock_request.assert_called_once()


@patch("onyx.connectors.linear.connector.request_with_retries")
def test_load_credentials_with_token_within_buffer_refreshes(
    mock_request: MagicMock,
) -> None:
    """Tokens that expire within the 5-minute buffer should trigger a refresh."""
    mock_request.return_value = _make_mock_response(
        ok=True, json_data=_refresh_response_payload()
    )
    connector = LinearConnector()

    # 60 seconds from now is well within the 300-second buffer.
    new_credentials = connector.load_credentials(
        {
            "access_token": _OLD_ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) + 60,
        }
    )

    assert new_credentials is not None
    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert connector.linear_api_key == f"Bearer {_FRESH_ACCESS_TOKEN}"
    mock_request.assert_called_once()


def test_load_credentials_with_no_known_keys_raises() -> None:
    """Empty credentials should raise ConnectorMissingCredentialError."""
    connector = LinearConnector()

    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})
