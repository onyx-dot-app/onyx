from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.google_drive import doc_conversion
from onyx.connectors.google_drive.doc_conversion import (
    FileExtractionResult,
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import Document, TextSection


def _convert(file: dict[str, Any]) -> Document | None:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.fetch_google_doc.return_value = None
    basic = FileExtractionResult(
        sections=[TextSection(text="basic text", link="https://drive/file")]
    )
    with (
        patch.object(
            doc_conversion, "_download_and_extract_sections_basic", return_value=basic
        ),
        patch.object(doc_conversion, "build_folder_path", return_value=[]),
    ):
        result = convert_drive_item_to_document(
            ops,
            allow_images=False,
            size_threshold=10_000,
            permission_sync_context=None,
            retriever_emails=["user@example.com"],
            file={
                "webViewLink": "https://drive.google.com/file/d/file/view",
                "modifiedTime": "2026-10-01T00:00:00+00:00",
                **file,
            },
        )
    assert result is None or isinstance(result, Document)
    return result


def test_uploaded_file_reports_its_mime_type_and_size() -> None:
    document = _convert(
        {
            "id": "file",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "size": "2048",
        }
    )

    assert document is not None
    assert document.source_mime_type == "application/pdf"
    assert document.source_size_bytes == 2048


def test_google_doc_reports_its_listed_size() -> None:
    document = _convert(
        {
            "id": "doc",
            "name": "A doc",
            "mimeType": GDriveMimeType.DOC.value,
            "size": "512",
        }
    )

    assert document is not None
    assert document.source_mime_type == GDriveMimeType.DOC.value
    assert document.source_size_bytes == 512


def test_google_doc_reports_its_mime_type_without_a_listed_size() -> None:
    document = _convert(
        {"id": "doc", "name": "A doc", "mimeType": GDriveMimeType.DOC.value}
    )

    assert document is not None
    assert document.source_mime_type == GDriveMimeType.DOC.value
    assert document.source_size_bytes is None


def test_file_over_the_size_threshold_is_skipped() -> None:
    document = _convert(
        {"id": "big", "name": "big.pdf", "mimeType": "application/pdf", "size": "20000"}
    )

    assert document is None
