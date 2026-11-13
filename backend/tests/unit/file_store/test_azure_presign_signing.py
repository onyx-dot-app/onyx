"""SAS signing of the Azure file store, with the Blob service mocked.

A user delegation key needs Entra ID, which Azurite does not offer, so the
workload identity path is covered here and by the live test in
external_dependency_unit/file_store/test_azure_blob_presign_identity.py.
"""

import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from azure.core.exceptions import HttpResponseError
from azure.storage.blob import UserDelegationKey

from onyx.file_store.azure_blob_file_store import AzureBlobBackedFileStore
from onyx.file_store.file_store import PresignedUrlsNotSupportedError

ACCOUNT_NAME = "onyxtest"
CONTAINER = "onyx-files"
BLOB = "onyx-files/public/snapshot.tar"


def _delegation_key() -> UserDelegationKey:
    key = UserDelegationKey()
    key.signed_oid = "00000000-0000-0000-0000-000000000001"
    key.signed_tid = "00000000-0000-0000-0000-000000000002"
    key.signed_start = "2026-01-01T00:00:00Z"
    key.signed_expiry = "2026-01-01T01:00:00Z"
    key.signed_service = "b"
    key.signed_version = "2025-01-05"
    key.value = base64.b64encode(b"k" * 32).decode()
    return key


def _client() -> MagicMock:
    client = MagicMock()
    client.account_name = ACCOUNT_NAME
    client.get_user_delegation_key.return_value = _delegation_key()
    blob_client = MagicMock()
    blob_client.url = f"https://{ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER}/{BLOB}"
    client.get_blob_client.return_value = blob_client
    return client


def _store(client: MagicMock, **kwargs: str) -> AzureBlobBackedFileStore:
    store = AzureBlobBackedFileStore(container_name=CONTAINER, **kwargs)
    store._get_blob_service_client = MagicMock(return_value=client)  # type: ignore[method-assign]
    return store


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_workload_identity_signs_a_user_delegation_sas_and_reuses_the_key() -> None:
    client = _client()
    store = _store(client, account_name=ACCOUNT_NAME)

    download = store._sign_download(CONTAINER, BLOB, 300)
    store._sign_download(CONTAINER, BLOB, 300)

    query = _query(download.url)
    assert query["skoid"] == [_delegation_key().signed_oid]
    assert query["sp"] == ["r"]
    assert query["sr"] == ["b"]
    client.get_user_delegation_key.assert_called_once()
    expiry = client.get_user_delegation_key.call_args.kwargs["key_expiry_time"]
    assert expiry - datetime.now(UTC) > timedelta(minutes=50)


def test_a_key_near_its_expiry_is_replaced() -> None:
    client = _client()
    store = _store(client, account_name=ACCOUNT_NAME)
    store._sign_download(CONTAINER, BLOB, 300)

    # Less time left than the longest URL lifetime.
    store._user_delegation_key_expiry = datetime.now(UTC) + timedelta(minutes=10)
    store._sign_download(CONTAINER, BLOB, 300)

    assert client.get_user_delegation_key.call_count == 2


def test_a_missing_role_means_presign_is_not_supported() -> None:
    client = _client()
    error = HttpResponseError(message="AuthorizationPermissionMismatch")
    error.status_code = 403
    client.get_user_delegation_key.side_effect = error
    store = _store(client, account_name=ACCOUNT_NAME)

    with pytest.raises(PresignedUrlsNotSupportedError):
        store._sign_download(CONTAINER, BLOB, 300)


def test_an_account_key_signs_a_service_sas() -> None:
    client = _client()
    store = _store(
        client,
        account_name=ACCOUNT_NAME,
        account_key=base64.b64encode(b"a" * 64).decode(),
    )

    download = store._sign_download(CONTAINER, BLOB, 300)

    query = _query(download.url)
    assert "skoid" not in query
    assert query["sig"]
    client.get_user_delegation_key.assert_not_called()


def test_a_connection_string_without_a_key_cannot_sign() -> None:
    client = _client()
    store = _store(
        client,
        connection_string=(
            f"BlobEndpoint=https://{ACCOUNT_NAME}.blob.core.windows.net/;"
            "SharedAccessSignature=sv=2025-01-05&sig=x"
        ),
    )

    with pytest.raises(PresignedUrlsNotSupportedError):
        store._sign_download(CONTAINER, BLOB, 300)
    client.get_user_delegation_key.assert_not_called()
