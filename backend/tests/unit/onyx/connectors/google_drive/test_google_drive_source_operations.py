from typing import Any
from unittest import mock

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive import source_operations
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    GoogleCredentialKind,
)
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.models import ConnectorMissingCredentialError

_ADMIN = "admin@co.com"
_CREDENTIALS = {
    DB_CREDENTIALS_DICT_TOKEN_KEY: "{}",
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY: _ADMIN,
}
_REFRESHED = {DB_CREDENTIALS_DICT_TOKEN_KEY: '{"token": "new"}'}
_RATE_LIMIT_BODY = (
    b'{"error": {"errors": [{"reason": "userRateLimitExceeded"}], '
    b'"message": "userRateLimitExceeded"}}'
)
_DISABLED_API_BODY = (
    b'{"error": {"errors": [{"reason": "accessNotConfigured"}], '
    b'"message": "Drive API has not been used in project 1"}}'
)


def _http_error(status: int, body: bytes = b"{}") -> HttpError:
    return HttpError(httplib2.Response({"status": status}), body)


def _provider(credentials: dict[str, str]) -> mock.Mock:
    provider = mock.Mock(spec=CredentialsProviderInterface)
    provider.get_credentials.return_value = credentials
    provider.__enter__ = mock.Mock(return_value=provider)
    provider.__exit__ = mock.Mock(return_value=None)
    return provider


def _gateway(
    provider: CredentialsProviderInterface | None = None,
) -> GoogleDriveSourceOperations:
    return GoogleDriveSourceOperations(
        credentials_provider=provider
        or OnyxStaticCredentialsProvider(None, "google_drive", dict(_CREDENTIALS))
    )


def _patch_creds(
    creds: object, refreshed: dict[str, str] | None = None
) -> "mock._patch[mock.MagicMock]":
    return mock.patch.object(
        source_operations, "get_google_creds", return_value=(creds, refreshed)
    )


def test_authenticate_writes_a_refreshed_token_back() -> None:
    """A refreshed OAuth token reaches the credentials provider (which the
    checks runner backs with the database) and the caller."""
    provider = _provider(dict(_CREDENTIALS))
    gateway = _gateway(provider)

    with _patch_creds(mock.Mock(spec=OAuthCredentials), _REFRESHED) as get_creds:
        auth = gateway.authenticate()
        gateway.authenticate()

    assert auth.kind == GoogleCredentialKind.OAUTH
    assert auth.primary_admin_email == _ADMIN
    assert auth.refreshed_credential_json == _REFRESHED
    provider.set_credentials.assert_called_once_with(_REFRESHED)
    # The credential loads once per gateway.
    get_creds.assert_called_once()
    provider.__enter__.assert_called_once()


def test_authenticate_reports_a_service_account() -> None:
    gateway = _gateway()

    with _patch_creds(mock.Mock(spec=ServiceAccountCredentials)):
        auth = gateway.authenticate()

    assert auth.kind == GoogleCredentialKind.SERVICE_ACCOUNT
    assert auth.refreshed_credential_json is None


def test_authenticate_requires_the_primary_admin() -> None:
    gateway = _gateway(_provider({DB_CREDENTIALS_DICT_TOKEN_KEY: "{}"}))

    with pytest.raises(ConnectorMissingCredentialError):
        gateway.authenticate()


def test_failed_token_refresh_leaves_as_a_gateway_error() -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations,
        "get_google_creds",
        side_effect=RefreshError("unauthorized_client: Client is unauthorized"),
    ):
        with pytest.raises(GoogleDriveRefreshError, match="unauthorized_client"):
            gateway.authenticate()


def test_connector_returns_the_refreshed_token_for_persistence() -> None:
    connector = GoogleDriveConnector(include_my_drives=True)

    with _patch_creds(mock.Mock(spec=OAuthCredentials), _REFRESHED):
        refreshed = connector.load_credentials(dict(_CREDENTIALS))

    assert refreshed == _REFRESHED
    assert connector.is_service_account is False
    assert connector.include_files_shared_with_me is False


def test_service_account_connector_includes_shared_files() -> None:
    connector = GoogleDriveConnector(include_my_drives=True)

    with _patch_creds(mock.Mock(spec=ServiceAccountCredentials)):
        connector.load_credentials(dict(_CREDENTIALS))

    assert connector.is_service_account is True
    assert connector.include_files_shared_with_me is True


@pytest.mark.parametrize(
    "body,reasons,access_denied",
    [
        (_DISABLED_API_BODY, ("accessNotConfigured",), True),
        # Google reports some rate limits as a 403; those are not denials.
        (_RATE_LIMIT_BODY, ("userRateLimitExceeded",), False),
    ],
)
def test_http_errors_leave_as_gateway_errors(
    body: bytes, reasons: tuple[str, ...], access_denied: bool
) -> None:
    gateway = _gateway()
    service = mock.Mock()
    service.files.return_value.get.return_value.execute.side_effect = _http_error(
        403, body
    )

    with mock.patch.object(GoogleDriveSourceOperations, "_drive", return_value=service):
        with pytest.raises(GoogleDriveHttpError) as raised:
            gateway.get_root_folder_id(user_email=_ADMIN)

    assert raised.value.status_code == 403
    assert raised.value.reasons == reasons
    assert raised.value.access_denied is access_denied
    assert isinstance(raised.value.__cause__, HttpError)


def test_generator_operations_translate_errors_raised_while_iterating() -> None:
    gateway = _gateway()

    def _failing_listing(**_kwargs: Any) -> Any:
        raise _http_error(404)
        yield

    with (
        mock.patch.object(GoogleDriveSourceOperations, "_drive"),
        mock.patch.object(
            source_operations,
            "execute_paginated_retrieval",
            side_effect=_failing_listing,
        ),
    ):
        listing = gateway.list_drives(user_email=_ADMIN, use_domain_admin_access=True)
        with pytest.raises(GoogleDriveHttpError) as raised:
            next(listing)

    assert raised.value.status_code == 404


def test_get_file_reads_a_denied_file_as_missing() -> None:
    gateway = _gateway()
    service = mock.Mock()
    service.files.return_value.get.return_value.execute.side_effect = _http_error(404)

    with mock.patch.object(GoogleDriveSourceOperations, "_drive", return_value=service):
        assert gateway.get_file(user_email=_ADMIN, file_id="f", fields="id") is None


@pytest.mark.parametrize(
    "variant,drive_id,expected",
    [
        (DriveCorpus.USER, None, {"corpora": "user"}),
        (
            DriveCorpus.DRIVE,
            "d1",
            {
                "corpora": "drive",
                "driveId": "d1",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            },
        ),
        (
            DriveCorpus.ALL_DRIVES,
            None,
            {
                "corpora": "allDrives",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            },
        ),
    ],
)
def test_list_files_sends_the_corpus_of_its_variant(
    variant: DriveCorpus, drive_id: str | None, expected: dict[str, object]
) -> None:
    gateway = _gateway()

    with (
        mock.patch.object(GoogleDriveSourceOperations, "_drive"),
        mock.patch.object(
            source_operations, "execute_paginated_retrieval", return_value=iter([])
        ) as retrieval,
    ):
        list(
            gateway.list_files(
                variant=variant,
                user_email=_ADMIN,
                drive_id=drive_id,
                query="trashed = false",
                fields="nextPageToken, files(id)",
            )
        )

    kwargs = retrieval.call_args.kwargs
    assert {key: kwargs[key] for key in expected} == expected
    if variant == DriveCorpus.USER:
        assert "supportsAllDrives" not in kwargs


def test_list_files_requires_a_drive_id_for_a_drive_listing() -> None:
    with pytest.raises(ValueError):
        next(
            _gateway().list_files(
                variant=DriveCorpus.DRIVE,
                user_email=_ADMIN,
                fields="nextPageToken, files(id)",
            )
        )


def test_list_files_requires_its_variant() -> None:
    with pytest.raises(TypeError, match="variant"):
        _gateway().list_files(  # ty: ignore[missing-argument]
            user_email=_ADMIN, fields="nextPageToken, files(id)"
        )
