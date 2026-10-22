from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ee.onyx.db.usage_export import get_usage_report_data
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import (
    DocumentBase,
    ImageSection,
    TabularSection,
    TextSection,
)
from onyx.db.models import FileRecord, User, UserFile
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.document_batch_storage import FileStoreDocumentBatchStorage
from onyx.file_store.file_store import FileStore
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.file_store.utils import verify_user_files
from onyx.server.onyx_api.ingestion import upsert_ingestion_doc
from onyx.server.onyx_api.models import IngestionDocument


@pytest.mark.parametrize(
    ("origin", "file_type"),
    [
        (FileOrigin.USER_FILE, "application/zip"),
        (FileOrigin.GENERATED_REPORT, "text/plain"),
    ],
)
def test_usage_report_requires_report_origin_and_zip_type(
    origin: FileOrigin, file_type: str
) -> None:
    file_store = MagicMock(spec=FileStore)
    content = BytesIO(b"report")
    file_store.read_file.return_value = content

    def has_file(file_id: str, file_origin: FileOrigin, file_type: str) -> bool:
        return (
            file_id == "report.zip"
            and file_origin == record.file_origin
            and file_type == record.file_type
        )

    record = FileRecord(file_origin=origin, file_type=file_type)
    file_store.has_file.side_effect = has_file
    with patch(
        "ee.onyx.db.usage_export.get_default_file_store", return_value=file_store
    ):
        with pytest.raises(ValueError, match="not found"):
            get_usage_report_data("report.zip")
        file_store.read_file.assert_not_called()
        record.file_origin = FileOrigin.GENERATED_REPORT
        record.file_type = "application/zip"
        assert get_usage_report_data("report.zip") is content


def test_batch_cleanup_does_not_match_another_connection_prefix() -> None:
    file_store = MagicMock(spec=FileStore)
    records = [
        FileRecord(file_id="iab/2/3/0.json"),
        FileRecord(file_id="iab/20/3/0.json"),
        FileRecord(file_id="iab/200/3/0.json"),
    ]
    file_store.list_files_by_prefix.side_effect = lambda prefix: [
        record for record in records if record.file_id.startswith(prefix)
    ]
    storage = FileStoreDocumentBatchStorage(2, 3, file_store)

    storage.cleanup_all_batches()

    file_store.delete_file.assert_called_once_with(
        "iab/2/3/0.json", error_on_missing=False
    )


def test_batch_recovery_rejects_another_connection() -> None:
    file_store = MagicMock(spec=FileStore)
    storage = FileStoreDocumentBatchStorage(2, 4, file_store)

    storage.update_old_batches_to_new_index_attempt(
        ["iab/20/3/0.json", "iab/2/3/1.json"]
    )

    file_store.change_file_id.assert_called_once_with(
        "iab/2/3/1.json", "iab/2/4/1.json"
    )


@pytest.mark.parametrize("reference", ["invalid", "missing", "mismatch"])
def test_user_file_descriptor_must_match_owned_record(reference: str) -> None:
    user_id = uuid4()
    user_file_id = uuid4()
    user_file = UserFile(id=user_file_id, user_id=user_id, file_id="owned-file")
    descriptor: FileDescriptor = {
        "id": "foreign-file" if reference == "mismatch" else "owned-file",
        "user_file_id": "invalid" if reference == "invalid" else str(user_file_id),
        "type": ChatFileType.PLAIN_TEXT,
    }
    with patch(
        "onyx.file_store.utils.get_user_file_by_id",
        return_value=None if reference == "missing" else user_file,
    ) as get_user_file:
        with pytest.raises(ValueError):
            verify_user_files([descriptor], user_id, MagicMock())
        get_user_file.return_value = user_file
        descriptor["user_file_id"] = str(user_file_id)
        descriptor["id"] = "owned-file"
        verify_user_files([descriptor], user_id, MagicMock())


@pytest.mark.parametrize("reference", ["document", "image", "text-image", "table"])
def test_ingestion_rejects_internal_file_references(reference: str) -> None:
    section: TextSection | ImageSection | TabularSection = TextSection(text="text")
    if reference == "image":
        section = ImageSection(image_file_id="foreign-file")
    elif reference == "text-image":
        section = TextSection(text="text", image_file_id="foreign-file")
    elif reference == "table":
        section = TabularSection(csv_file_id="foreign-file", link="https://example.com")
    document = DocumentBase(
        id="document",
        semantic_identifier="Document",
        metadata={},
        sections=[section],
        file_id="foreign-file" if reference == "document" else None,
    )
    with patch(
        "onyx.server.onyx_api.ingestion.get_connector_credential_pair_from_id",
        return_value=None,
    ) as get_connection:
        with pytest.raises(OnyxError) as error:
            upsert_ingestion_doc(
                IngestionDocument(document=document), User(id=uuid4()), MagicMock()
            )
        assert error.value.error_code == OnyxErrorCode.VALIDATION_ERROR
        get_connection.assert_not_called()
