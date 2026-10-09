"""Credential handling for the Linear connector: a personal API key is sent
as is, an OAuth token near expiry is refreshed under the credential
provider's lock, and the refresh keeps the stored refresh token when Linear
omits one."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.linear.connector import LinearConnector, refresh_oauth_token
from onyx.connectors.models import ConnectorMissingCredentialError

OPS = "onyx.connectors.linear.connector"
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


@patch(f"{OPS}.request_with_retries")
def test_refresh_returns_new_credentials(mock_request: MagicMock) -> None:
    mock_request.return_value = _make_mock_response(
        ok=True, json_data=_refresh_response_payload()
    )

    before = time.time()
    new_credentials = refresh_oauth_token({"refresh_token": _REFRESH_TOKEN_VALUE})
    after = time.time()

    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert new_credentials["refresh_token"] == _NEW_REFRESH_TOKEN_VALUE
    assert int(before + _EXPIRES_IN_SECONDS) <= new_credentials["expire_at"]
    assert new_credentials["expire_at"] <= int(after + _EXPIRES_IN_SECONDS)
    call_kwargs = mock_request.call_args.kwargs
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"] == "https://api.linear.app/oauth/token"
    assert call_kwargs["data"]["grant_type"] == "refresh_token"
    assert call_kwargs["data"]["refresh_token"] == _REFRESH_TOKEN_VALUE


@patch(f"{OPS}.request_with_retries")
def test_refresh_keeps_the_stored_refresh_token_when_omitted(
    mock_request: MagicMock,
) -> None:
    mock_request.return_value = _make_mock_response(
        ok=True,
        json_data={
            "access_token": _FRESH_ACCESS_TOKEN,
            "expires_in": _EXPIRES_IN_SECONDS,
        },
    )

    new_credentials = refresh_oauth_token({"refresh_token": _REFRESH_TOKEN_VALUE})

    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert new_credentials["refresh_token"] == _REFRESH_TOKEN_VALUE


def test_refresh_without_a_refresh_token_raises() -> None:
    with pytest.raises(ConnectorMissingCredentialError):
        refresh_oauth_token({"access_token": _OLD_ACCESS_TOKEN})


@patch(f"{OPS}.request_with_retries")
def test_refresh_non_ok_response_raises(mock_request: MagicMock) -> None:
    mock_request.return_value = _make_mock_response(ok=False, text="invalid_grant")

    with pytest.raises(RuntimeError, match="Failed to refresh token"):
        refresh_oauth_token({"refresh_token": _REFRESH_TOKEN_VALUE})


def test_an_api_key_is_sent_as_is() -> None:
    connector = LinearConnector()

    assert connector.load_credentials({"linear_api_key": "api-key-value"}) is None
    assert connector._api_key() == "api-key-value"


def test_an_access_token_without_expiry_is_a_bearer_token() -> None:
    connector = LinearConnector()

    assert connector.load_credentials({"access_token": _OLD_ACCESS_TOKEN}) is None
    assert connector._api_key() == f"Bearer {_OLD_ACCESS_TOKEN}"


@patch(f"{OPS}.request_with_retries")
def test_a_token_with_time_left_is_not_refreshed(mock_request: MagicMock) -> None:
    connector = LinearConnector()

    new_credentials = connector.load_credentials(
        {
            "access_token": _OLD_ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) + _EXPIRES_IN_SECONDS,
        }
    )

    assert new_credentials is None
    assert connector._api_key() == f"Bearer {_OLD_ACCESS_TOKEN}"
    mock_request.assert_not_called()


@pytest.mark.parametrize("seconds_left", [-10, 60], ids=["expired", "within buffer"])
@patch(f"{OPS}.request_with_retries")
def test_an_expiring_token_is_refreshed_and_handed_back(
    mock_request: MagicMock, seconds_left: int
) -> None:
    mock_request.return_value = _make_mock_response(
        ok=True, json_data=_refresh_response_payload()
    )
    connector = LinearConnector()

    new_credentials = connector.load_credentials(
        {
            "access_token": _OLD_ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) + seconds_left,
        }
    )

    assert new_credentials is not None
    assert new_credentials["access_token"] == _FRESH_ACCESS_TOKEN
    assert new_credentials["refresh_token"] == _NEW_REFRESH_TOKEN_VALUE
    assert connector._api_key() == f"Bearer {_FRESH_ACCESS_TOKEN}"
    mock_request.assert_called_once()


def test_unknown_credentials_raise_on_first_use() -> None:
    connector = LinearConnector()
    connector.load_credentials({})

    with pytest.raises(ConnectorMissingCredentialError):
        connector._api_key()


def test_no_credentials_raise_on_first_use() -> None:
    with pytest.raises(ConnectorMissingCredentialError):
        LinearConnector()._api_key()


@patch(f"{OPS}.request_with_retries")
def test_a_db_credential_is_refreshed_under_the_providers_lock(
    mock_request: MagicMock,
) -> None:
    mock_request.return_value = _make_mock_response(
        ok=True, json_data=_refresh_response_payload()
    )
    expiring: dict[str, Any] = {
        "access_token": _OLD_ACCESS_TOKEN,
        "refresh_token": _REFRESH_TOKEN_VALUE,
        "expire_at": int(time.time()) - 10,
    }
    provider = MagicMock()
    provider.get_credentials.return_value = expiring
    connector = LinearConnector()
    connector.set_credentials_provider(provider)

    assert connector._api_key() == f"Bearer {_FRESH_ACCESS_TOKEN}"

    # Read, lock, read again, refresh, store: a sync that took the lock first
    # leaves a fresh token behind, which the second read sees.
    provider.__enter__.assert_called_once()
    assert provider.get_credentials.call_count == 2
    stored: dict[str, Any] = provider.set_credentials.call_args.args[0]
    assert stored["access_token"] == _FRESH_ACCESS_TOKEN
    assert stored["refresh_token"] == _NEW_REFRESH_TOKEN_VALUE
    mock_request.assert_called_once()


@patch(f"{OPS}.request_with_retries")
def test_a_token_another_sync_refreshed_is_not_refreshed_again(
    mock_request: MagicMock,
) -> None:
    provider = MagicMock()
    provider.get_credentials.side_effect = [
        {
            "access_token": _OLD_ACCESS_TOKEN,
            "refresh_token": _REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) - 10,
        },
        {
            "access_token": _FRESH_ACCESS_TOKEN,
            "refresh_token": _NEW_REFRESH_TOKEN_VALUE,
            "expire_at": int(time.time()) + _EXPIRES_IN_SECONDS,
        },
    ]
    connector = LinearConnector()
    connector.set_credentials_provider(provider)

    assert connector._api_key() == f"Bearer {_FRESH_ACCESS_TOKEN}"
    assert connector._api_key() == f"Bearer {_FRESH_ACCESS_TOKEN}"

    mock_request.assert_not_called()
    provider.set_credentials.assert_not_called()
    assert provider.get_credentials.call_count == 2
