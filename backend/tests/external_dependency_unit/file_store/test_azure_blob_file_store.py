"""Tests for AzureBlobBackedFileStore against a real Azure Blob endpoint.

Runs against Azurite, Microsoft's official Azure Storage emulator (the role
MinIO plays for the S3 backend tests):

    docker run -d -p 10000:10000 mcr.microsoft.com/azure-storage/azurite \
        azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck

(--skipApiVersionCheck covers the window where the azure-storage-blob SDK
speaks a service API version newer than the published Azurite image.)

Skips cleanly when no Azurite endpoint is reachable.
"""

import os
import socket
import uuid
from collections.abc import Generator
from io import BytesIO
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.file_store.azure_blob_file_store import AzureBlobBackedFileStore
from onyx.utils.logger import setup_logger

logger = setup_logger()

TEST_CONTAINER_NAME = "onyx-file-store-tests"

# Azurite's well-known development-storage account.
AZURITE_ACCOUNT_NAME = "devstoreaccount1"
AZURITE_ACCOUNT_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/"
    "KBHBeksoGMGw=="
)


def _azurite_blob_endpoint() -> str:
    return os.environ.get(
        "AZURITE_BLOB_ENDPOINT_FOR_TEST",
        f"http://127.0.0.1:10000/{AZURITE_ACCOUNT_NAME}",
    )


def _azurite_connection_string() -> str:
    endpoint = _azurite_blob_endpoint()
    return (
        "DefaultEndpointsProtocol=http;"
        f"AccountName={AZURITE_ACCOUNT_NAME};"
        f"AccountKey={AZURITE_ACCOUNT_KEY};"
        f"BlobEndpoint={endpoint};"
    )


def _azurite_reachable() -> bool:
    parsed = urlparse(_azurite_blob_endpoint())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 10000
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _azurite_reachable(),
    reason="Azurite is not reachable (set AZURITE_BLOB_ENDPOINT_FOR_TEST or run "
    "the mcr.microsoft.com/azure-storage/azurite container)",
)


def _make_store(azure_prefix: str) -> AzureBlobBackedFileStore:
    return AzureBlobBackedFileStore(
        container_name=TEST_CONTAINER_NAME,
        azure_prefix=azure_prefix,
        connection_string=_azurite_connection_string(),
    )


@pytest.fixture
def file_store(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[AzureBlobBackedFileStore, None, None]:
    """AzureBlobBackedFileStore against Azurite with a unique per-test prefix."""
    store = _make_store(azure_prefix=f"test-files-{uuid.uuid4()}")
    store.initialize()

    yield store

    # Remove all blobs written under this test's unique prefix.
    try:
        client = store._get_blob_service_client()
        container_client = client.get_container_client(TEST_CONTAINER_NAME)
        blob_names = [
            blob.name
            for blob in container_client.list_blobs(
                name_starts_with=f"{store._azure_prefix}/"
            )
        ]
        for blob_name in blob_names:
            container_client.delete_blob(blob_name)
        if blob_names:
            logger.info("Cleaned up %s test blobs from Azurite", len(blob_names))
    except Exception as e:
        logger.warning("Failed to cleanup test blobs: %s", e)


class TestAzureBlobBackedFileStore:
    def test_store_initialization_is_idempotent(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        # A second initialize must not fail on the existing container
        file_store.initialize()

        client = file_store._get_blob_service_client()
        assert client.get_container_client(TEST_CONTAINER_NAME).exists()

    def test_save_and_read_text_file(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        content = "Hello from the Azure file store test.\nSecond line."
        file_id = file_store.save_file(
            content=BytesIO(content.encode("utf-8")),
            display_name="test.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )

        read_back = file_store.read_file(file_id).read().decode("utf-8")
        assert read_back == content

        record = file_store.read_file_record(file_id)
        assert record.bucket_name == TEST_CONTAINER_NAME
        assert record.object_key.startswith(file_store._azure_prefix)
        assert record.file_type == "text/plain"

        file_store.delete_file(file_id)

    def test_save_and_read_binary_file(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        content = bytes(range(256)) * 64
        file_id = file_store.save_file(
            content=BytesIO(content),
            display_name="test.bin",
            file_origin=FileOrigin.OTHER,
            file_type="application/octet-stream",
        )

        assert file_store.read_file(file_id).read() == content
        file_store.delete_file(file_id)

    def test_read_with_tempfile(self, file_store: AzureBlobBackedFileStore) -> None:
        content = b"tempfile read path" * 1024
        file_id = file_store.save_file(
            content=BytesIO(content),
            display_name="large.bin",
            file_origin=FileOrigin.OTHER,
            file_type="application/octet-stream",
        )

        with file_store.read_file(file_id, use_tempfile=True) as temp_file:
            assert temp_file.read() == content
        file_store.delete_file(file_id)

    def test_save_overwrites_existing_file_id(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        file_id = str(uuid.uuid4())
        for content in (b"first version", b"second version"):
            file_store.save_file(
                content=BytesIO(content),
                display_name="overwrite.txt",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                file_id=file_id,
            )

        assert file_store.read_file(file_id).read() == b"second version"
        file_store.delete_file(file_id)

    def test_has_file(self, file_store: AzureBlobBackedFileStore) -> None:
        file_id = file_store.save_file(
            content=BytesIO(b"content"),
            display_name="has.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )

        assert file_store.has_file(
            file_id=file_id, file_origin=FileOrigin.OTHER, file_type="text/plain"
        )
        assert not file_store.has_file(
            file_id=file_id, file_origin=FileOrigin.CHAT_UPLOAD, file_type="text/plain"
        )
        assert not file_store.has_file(
            file_id=str(uuid.uuid4()),
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        file_store.delete_file(file_id)

    def test_get_file_size(self, file_store: AzureBlobBackedFileStore) -> None:
        content = b"exactly this many bytes"
        file_id = file_store.save_file(
            content=BytesIO(content),
            display_name="sized.bin",
            file_origin=FileOrigin.OTHER,
            file_type="application/octet-stream",
        )

        assert file_store.get_file_size(file_id) == len(content)
        file_store.delete_file(file_id)

    def test_delete_file(self, file_store: AzureBlobBackedFileStore) -> None:
        file_id = file_store.save_file(
            content=BytesIO(b"to delete"),
            display_name="delete.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        record = file_store.read_file_record(file_id)

        file_store.delete_file(file_id)

        client = file_store._get_blob_service_client()
        blob_client = client.get_blob_client(
            container=record.bucket_name, blob=record.object_key
        )
        assert not blob_client.exists()
        with pytest.raises(RuntimeError):
            file_store.delete_file(file_id)

    def test_delete_file_missing_no_error(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        file_store.delete_file(str(uuid.uuid4()), error_on_missing=False)

    def test_delete_file_tolerates_missing_blob(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        file_id = file_store.save_file(
            content=BytesIO(b"blob vanishes"),
            display_name="vanish.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        record = file_store.read_file_record(file_id)

        # Delete the blob out-of-band; delete_file must still clean up the record
        client = file_store._get_blob_service_client()
        client.get_blob_client(
            container=record.bucket_name, blob=record.object_key
        ).delete_blob()

        file_store.delete_file(file_id)
        assert not file_store.has_file(
            file_id=file_id, file_origin=FileOrigin.OTHER, file_type="text/plain"
        )

    def test_change_file_id(self, file_store: AzureBlobBackedFileStore) -> None:
        content = b"rename me"
        old_file_id = file_store.save_file(
            content=BytesIO(content),
            display_name="rename.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        new_file_id = str(uuid.uuid4())

        file_store.change_file_id(old_file_id, new_file_id)

        assert file_store.read_file(new_file_id).read() == content
        assert not file_store.has_file(
            file_id=old_file_id, file_origin=FileOrigin.OTHER, file_type="text/plain"
        )
        file_store.delete_file(new_file_id)

    def test_get_file_with_mime_type(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        file_id = file_store.save_file(
            content=BytesIO(png_header),
            display_name="image.png",
            file_origin=FileOrigin.OTHER,
            file_type="image/png",
        )

        result = file_store.get_file_with_mime_type(file_id)
        assert result is not None
        assert result.data == png_header
        assert result.mime_type == "image/png"
        file_store.delete_file(file_id)

    def test_db_failure_on_fresh_save_cleans_up_blob(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        """A failed DB write for a brand-new file must remove the uploaded blob."""
        file_id = str(uuid.uuid4())
        object_key = file_store._get_object_key(file_id)

        with patch(
            "onyx.file_store.azure_blob_file_store.upsert_filerecord",
            side_effect=RuntimeError("simulated DB failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated DB failure"):
                file_store.save_file(
                    content=BytesIO(b"never persisted"),
                    display_name="fresh.txt",
                    file_origin=FileOrigin.OTHER,
                    file_type="text/plain",
                    file_id=file_id,
                )

        client = file_store._get_blob_service_client()
        blob_client = client.get_blob_client(
            container=TEST_CONTAINER_NAME, blob=object_key
        )
        assert not blob_client.exists()

    def test_db_failure_on_overwrite_preserves_blob(
        self, file_store: AzureBlobBackedFileStore
    ) -> None:
        """A failed overwrite must NOT delete the blob the existing record references."""
        file_id = str(uuid.uuid4())
        file_store.save_file(
            content=BytesIO(b"original"),
            display_name="overwrite-fail.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        with patch(
            "onyx.file_store.azure_blob_file_store.upsert_filerecord",
            side_effect=RuntimeError("simulated DB failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated DB failure"):
                file_store.save_file(
                    content=BytesIO(b"replacement"),
                    display_name="overwrite-fail.txt",
                    file_origin=FileOrigin.OTHER,
                    file_type="text/plain",
                    file_id=file_id,
                )

        # The record survives and its blob is still readable (the upload itself
        # succeeded before the DB failure, so content is the new version)
        assert file_store.has_file(
            file_id=file_id, file_origin=FileOrigin.OTHER, file_type="text/plain"
        )
        assert file_store.read_file(file_id).read() == b"replacement"
        file_store.delete_file(file_id)

    def test_account_key_auth(
        self,
        db_session: Session,  # noqa: ARG002
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """The account-name + account-key auth path (vs connection string)."""
        store = AzureBlobBackedFileStore(
            container_name=TEST_CONTAINER_NAME,
            azure_prefix=f"test-files-{uuid.uuid4()}",
            account_name=AZURITE_ACCOUNT_NAME,
            account_url=_azurite_blob_endpoint(),
            account_key=AZURITE_ACCOUNT_KEY,
        )
        store.initialize()

        content = b"account key auth"
        file_id = store.save_file(
            content=BytesIO(content),
            display_name="auth.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        assert store.read_file(file_id).read() == content
        store.delete_file(file_id)
