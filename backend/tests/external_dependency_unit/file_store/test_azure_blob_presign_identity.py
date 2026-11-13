"""Presigned URLs from an Entra ID identity against a real Azure storage account.

This is the AKS workload identity path: no account key, so the store signs a
user delegation SAS. Azurite has no Entra ID, so this test needs a real account
and skips without one:

    AZURE_PRESIGN_TEST_ACCOUNT_NAME=<account> pytest <this file>

DefaultAzureCredential picks up the identity (workload identity, managed
identity, or a local `az login`). Grant it Storage Blob Data Contributor on the
account. Turn off shared key access on the account to prove no key is used.
"""

import hashlib
import os
import uuid
from collections.abc import Generator
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.file_store.azure_blob_file_store import AzureBlobBackedFileStore
from onyx.file_store.models import PresignedRequest

ACCOUNT_NAME = os.environ.get("AZURE_PRESIGN_TEST_ACCOUNT_NAME")
CONTAINER_NAME = "onyx-presign-identity-tests"
CONTENT = b"a craft session snapshot"

pytestmark = pytest.mark.skipif(
    not ACCOUNT_NAME,
    reason="Set AZURE_PRESIGN_TEST_ACCOUNT_NAME to a storage account the "
    "DefaultAzureCredential identity can use",
)


def _send(request: PresignedRequest, content: bytes | None = None) -> httpx.Response:
    return httpx.request(
        request.method, request.url, headers=request.headers, content=content
    )


def _assert_user_delegation_sas(url: str) -> None:
    query = parse_qs(urlparse(url).query)
    assert "skoid" in query, "expected a user delegation SAS"


@pytest.fixture
def file_store(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[AzureBlobBackedFileStore, None, None]:
    assert ACCOUNT_NAME is not None
    store = AzureBlobBackedFileStore(
        container_name=CONTAINER_NAME,
        azure_prefix=f"test-files-{uuid.uuid4()}",
        account_name=ACCOUNT_NAME,
    )
    store.initialize()

    yield store

    container = store._get_blob_service_client().get_container_client(CONTAINER_NAME)
    for blob in container.list_blobs(name_starts_with=f"{store._azure_prefix}/"):
        container.delete_blob(blob.name)


def test_an_upload_and_a_download_round_trip_without_an_account_key(
    file_store: AzureBlobBackedFileStore,
) -> None:
    upload = file_store.presign_upload(
        display_name="snapshot.tar",
        file_origin=FileOrigin.OTHER,
        file_type="application/x-tar",
        size=len(CONTENT),
        sha256=hashlib.sha256(CONTENT).hexdigest(),
    )
    _assert_user_delegation_sas(upload.request.url)

    put = _send(upload.request, CONTENT)
    assert put.status_code == 201, put.text
    file_id = file_store.finalize_presigned_upload(upload.pending_upload_id)

    download = file_store.presign_download(file_id)
    _assert_user_delegation_sas(download.url)
    get = _send(download)
    assert get.status_code == 200, get.text
    assert get.content == CONTENT

    # Create permission only: the same URL cannot replace the blob.
    assert _send(upload.request, CONTENT[:-1] + b"!").status_code >= 400
    assert file_store.read_file(file_id).read() == CONTENT
    file_store.delete_file(file_id)


def test_a_download_url_for_a_saved_file_reads_it(
    file_store: AzureBlobBackedFileStore,
) -> None:
    file_id = file_store.save_file(
        content=BytesIO(CONTENT),
        display_name="snapshot.tar",
        file_origin=FileOrigin.OTHER,
        file_type="application/x-tar",
    )

    response = _send(file_store.presign_download(file_id))

    assert response.status_code == 200, response.text
    assert response.content == CONTENT
    file_store.delete_file(file_id)
