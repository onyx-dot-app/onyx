"""A token refresh that gets no answer from Google raises
GoogleUnreachableError. Only a refresh that Google rejects reads as a bad
credential."""

import json
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.generic_row import generic_row_error
from onyx.connectors.exceptions import UnreachableValidationError
from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.google_drive.source_operations import is_google_timeout
from onyx.connectors.google_utils import google_auth
from onyx.connectors.google_utils.google_auth import (
    GoogleUnreachableError,
    get_google_creds,
    get_google_oauth_creds,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_DICT_TOKEN_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import connector as connector_api

_EXPIRED_TOKEN = json.dumps(
    {
        "client_id": "client",
        "client_secret": "secret",
        "refresh_token": "refresh",
        "token": "old",
        "expiry": "2020-01-01T00:00:00Z",
    }
)
_OAUTH_CREDENTIALS = {
    DB_CREDENTIALS_DICT_TOKEN_KEY: _EXPIRED_TOKEN,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY: "admin@co.com",
}


def _transport_error(cause: Exception) -> TransportError:
    """A token request that got no answer, as google-auth raises it."""
    try:
        raise TransportError(cause) from cause
    except TransportError as error:
        return error


def _refresh_raises(error: Exception) -> "mock._patch[MagicMock]":
    return patch.object(
        google_auth.OAuthCredentials, "refresh", autospec=True, side_effect=error
    )


@pytest.mark.parametrize(
    "error",
    [
        _transport_error(requests.ConnectionError("refused")),
        _transport_error(requests.ReadTimeout("read timed out")),
        TimeoutError(),
    ],
)
def test_no_answer_raises_unreachable(error: Exception) -> None:
    with _refresh_raises(error), pytest.raises(GoogleUnreachableError) as caught:
        get_google_oauth_creds(_EXPIRED_TOKEN, DocumentSource.GOOGLE_DRIVE)
    assert caught.value.__cause__ is error


def test_a_timeout_stays_visible_through_the_wrapper() -> None:
    error = _transport_error(requests.ReadTimeout("read timed out"))
    with _refresh_raises(error), pytest.raises(GoogleUnreachableError) as caught:
        get_google_oauth_creds(_EXPIRED_TOKEN, DocumentSource.GOOGLE_DRIVE)
    assert is_google_timeout(caught.value)


def test_a_rejected_refresh_still_returns_none() -> None:
    with _refresh_raises(RefreshError("invalid_grant: Token has been revoked.")):
        assert (
            get_google_oauth_creds(_EXPIRED_TOKEN, DocumentSource.GOOGLE_DRIVE) is None
        )
        with pytest.raises(PermissionError):
            get_google_creds(dict(_OAUTH_CREDENTIALS), DocumentSource.GOOGLE_DRIVE)


def test_get_google_creds_does_not_call_no_answer_a_rejection() -> None:
    with (
        _refresh_raises(_transport_error(requests.ConnectionError("refused"))),
        pytest.raises(GoogleUnreachableError),
    ):
        get_google_creds(dict(_OAUTH_CREDENTIALS), DocumentSource.GOOGLE_DRIVE)


def test_a_service_account_refresh_with_no_answer_raises_unreachable() -> None:
    with patch.object(
        google_auth.ServiceAccountCredentials, "from_service_account_info"
    ) as build:
        build.return_value.valid = False
        build.return_value.refresh.side_effect = _transport_error(
            requests.ConnectionError("refused")
        )
        with pytest.raises(GoogleUnreachableError):
            get_google_creds(
                {DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: "{}"},
                DocumentSource.GOOGLE_DRIVE,
            )


def test_gmail_shows_no_answer_as_unreachable() -> None:
    with (
        _refresh_raises(_transport_error(requests.ConnectionError("refused"))),
        pytest.raises(GoogleUnreachableError) as caught,
    ):
        GmailConnector().load_credentials(dict(_OAUTH_CREDENTIALS))

    row = generic_row_error(caught.value)
    assert isinstance(row, UnreachableValidationError)
    assert row.summary == "Cannot reach the source"


def _check_drive_tokens() -> object:
    credential = MagicMock()
    credential.credential_json.get_value.return_value = dict(_OAUTH_CREDENTIALS)
    with (
        patch.object(
            connector_api,
            "fetch_credential_by_id_for_user",
            return_value=credential,
        ),
        patch.object(
            connector_api, "is_credential_usable_for_source", return_value=True
        ),
        patch.object(
            connector_api,
            "to_source_credential_json",
            side_effect=lambda _source, stored: stored,
        ),
    ):
        return connector_api.check_drive_tokens(
            credential_id=1, user=MagicMock(), db_session=MagicMock()
        )


def test_check_auth_reports_no_answer_as_a_gateway_error() -> None:
    with (
        _refresh_raises(_transport_error(requests.ConnectionError("refused"))),
        pytest.raises(OnyxError) as caught,
    ):
        _check_drive_tokens()
    assert caught.value.error_code == OnyxErrorCode.BAD_GATEWAY


def test_check_auth_reports_a_rejected_token_as_unauthenticated() -> None:
    with _refresh_raises(RefreshError("invalid_grant")):
        status = _check_drive_tokens()
    assert status == connector_api.AuthStatus(authenticated=False)
