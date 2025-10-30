from collections.abc import Iterable
from unittest.mock import patch

from onyx.connectors.google_drive.doc_conversion import (
    _download_and_extract_sections_basic,
)
from onyx.connectors.google_drive.doc_conversion import _process_csv_in_chunks
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.models import TextSection


class _DummyFilesResource:
    def export_media(self, *, fileId: str, mimeType: str) -> object:  # noqa: D401
        # Params are exercised implicitly; return any object for the downloader stub.
        return object()


class _DummyDriveService:
    def files(self) -> _DummyFilesResource:  # noqa: D401
        return _DummyFilesResource()


def _sections_to_lines(sections: Iterable[TextSection]) -> list[str]:
    lines: list[str] = []
    for section in sections:
        lines.extend(section.text.strip().splitlines())
    return lines


def test_process_csv_in_chunks_splits_large_csv() -> None:
    header = "col1,col2"
    rows = [f"{idx},{idx + 1}" for idx in range(100)]
    csv_bytes = (header + "\n" + "\n".join(rows)).encode("utf-8")

    sections = _process_csv_in_chunks(
        csv_bytes, link="https://example.com", chunk_size=50
    )

    assert len(sections) > 1
    combined_lines = _sections_to_lines(sections)
    assert combined_lines[0] == header
    assert rows[-1] in combined_lines


def test_download_and_extract_sections_basic_skips_extremely_large_spreadsheet() -> (
    None
):
    spreadsheet_file = {
        "id": "file-id",
        "name": "large-sheet",
        "mimeType": GDriveMimeType.SPREADSHEET.value,
        "webViewLink": "https://example.com",
    }
    dummy_service = _DummyDriveService()
    oversized_csv = b"col1,col2\n1,2\n"

    with patch(
        "onyx.connectors.google_drive.doc_conversion._download_request",
        return_value=oversized_csv,
    ), patch(
        "onyx.connectors.google_drive.doc_conversion.MAX_SPREADSHEET_SIZE",
        len(oversized_csv) - 1,
    ), patch(
        "onyx.connectors.google_drive.doc_conversion.LARGE_SPREADSHEET_SIZE_THRESHOLD",
        len(oversized_csv) - 10,
    ):
        sections = _download_and_extract_sections_basic(
            spreadsheet_file,
            dummy_service,
            allow_images=False,
            size_threshold=1_000,
        )

    assert len(sections) == 1
    assert "[File too large to process" in sections[0].text


def test_download_and_extract_sections_basic_chunks_large_spreadsheet() -> None:
    spreadsheet_file = {
        "id": "file-id",
        "name": "chunk-sheet",
        "mimeType": GDriveMimeType.SPREADSHEET.value,
        "webViewLink": "https://example.com/chunk",
    }
    dummy_service = _DummyDriveService()
    csv_body = (
        "col1,col2\n" + "\n".join(f"{idx},{idx + 1}" for idx in range(20))
    ).encode("utf-8")
    expected_sections = [TextSection(link="https://example.com/chunk", text="chunk-1")]

    with patch(
        "onyx.connectors.google_drive.doc_conversion._download_request",
        return_value=csv_body,
    ), patch(
        "onyx.connectors.google_drive.doc_conversion.MAX_SPREADSHEET_SIZE",
        len(csv_body) + 50,
    ), patch(
        "onyx.connectors.google_drive.doc_conversion.LARGE_SPREADSHEET_SIZE_THRESHOLD",
        len(csv_body) - 10,
    ), patch(
        "onyx.connectors.google_drive.doc_conversion._process_csv_in_chunks",
        return_value=expected_sections,
    ) as mock_chunk:
        sections = _download_and_extract_sections_basic(
            spreadsheet_file,
            dummy_service,
            allow_images=False,
            size_threshold=1_000,
        )

    assert sections == expected_sections
    mock_chunk.assert_called_once_with(csv_body, spreadsheet_file["webViewLink"])
