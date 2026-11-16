"""A failed download fails its document. It must not look like a file with no
content, which the run drops with no failure and never fetches again."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.google_drive import doc_conversion
from onyx.connectors.google_drive.doc_conversion import (
    convert_drive_item_to_document,
    onyx_document_id_from_drive_file,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import ConnectorFailure, Document

_LISTER = "lister@example.com"
_OWNER = "owner@example.com"
# A type with no branch of its own, read by its extension.
_MARKDOWN_FILE = {
    "id": "file_1",
    "name": "notes.md",
    "mimeType": "text/markdown",
    "webViewLink": "https://drive.google.com/file/d/file_1/view",
    "modifiedTime": "2026-10-01T00:00:00+00:00",
}
_IMAGE_FILE = {**_MARKDOWN_FILE, "name": "photo.png", "mimeType": "image/png"}


def _http_error(status: int, reasons: tuple[str, ...] = ()) -> GoogleDriveHttpError:
    return GoogleDriveHttpError(
        status_code=status,
        reasons=reasons,
        access_denied=status in (403, 404) and not reasons,
        message=f"HTTP {status}",
    )


def _convert(
    download: object, file: dict[str, str], allow_images: bool = False
) -> tuple[Document | ConnectorFailure | None, MagicMock]:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.download_file.side_effect = download
    with patch.object(doc_conversion, "build_folder_path", return_value=[]):
        result = convert_drive_item_to_document(
            ops,
            allow_images=allow_images,
            size_threshold=10_000,
            permission_sync_context=None,
            retriever_emails=[_LISTER, _OWNER],
            file=file,
        )
    return result, ops


@pytest.mark.parametrize(
    "error", [_http_error(500), _http_error(403, ("userRateLimitExceeded",))]
)
def test_a_failed_download_is_a_failure_not_a_skip(error: GoogleDriveHttpError) -> None:
    result, _ = _convert(error, _MARKDOWN_FILE)

    assert isinstance(result, ConnectorFailure)
    assert result.failed_document is not None
    assert result.failed_document.document_id == onyx_document_id_from_drive_file(
        _MARKDOWN_FILE
    )
    assert result.exception is error


def test_a_download_the_lister_is_denied_goes_to_the_next_user() -> None:
    with patch.object(doc_conversion, "extract_file_text", return_value="body"):
        result, ops = _convert([_http_error(403), b"# Title"], _MARKDOWN_FILE)

    assert isinstance(result, Document)
    assert [call.kwargs["user_email"] for call in ops.download_file.call_args_list] == [
        _LISTER,
        _OWNER,
    ]


def test_a_failed_image_download_is_a_failure() -> None:
    result, _ = _convert(_http_error(500), _IMAGE_FILE, allow_images=True)

    assert isinstance(result, ConnectorFailure)


def test_a_file_that_cannot_be_parsed_is_still_skipped() -> None:
    with patch.object(
        doc_conversion, "extract_file_text", side_effect=ValueError("bad file")
    ):
        result, _ = _convert([b"\x00\x01"], _MARKDOWN_FILE)

    assert result is None
