import io
import zipfile
from unittest.mock import MagicMock
from unittest.mock import patch
from zipfile import BadZipFile

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from onyx.configs.constants import FileOrigin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.connector import upload_files


def _create_test_zip() -> bytes:
    """Create a simple in-memory zip file containing two text files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("file1.txt", "hello")
        zf.writestr("file2.txt", "world")
    return buf.getvalue()


def _make_upload_file(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@patch("onyx.server.documents.connector.get_default_file_store")
def test_upload_zip_with_unzip_true_extracts_files(
    mock_get_store: MagicMock,
) -> None:
    """When unzip=True (default), a zip upload is extracted into individual files."""
    mock_store = MagicMock()
    mock_store.save_file.side_effect = lambda **kwargs: f"id-{kwargs['display_name']}"
    mock_get_store.return_value = mock_store

    zip_bytes = _create_test_zip()
    upload = _make_upload_file(zip_bytes, "test.zip", "application/zip")

    result = upload_files([upload], FileOrigin.CONNECTOR)

    # Should have extracted the two individual files, not stored the zip itself
    assert len(result.file_paths) == 2
    assert "id-file1.txt" in result.file_paths
    assert "id-file2.txt" in result.file_paths
    assert "file1.txt" in result.file_names
    assert "file2.txt" in result.file_names


@patch("onyx.server.documents.connector.get_default_file_store")
def test_upload_zip_with_unzip_false_stores_zip_as_is(
    mock_get_store: MagicMock,
) -> None:
    """When unzip=False, the zip file is stored as-is without extraction."""
    mock_store = MagicMock()
    mock_store.save_file.return_value = "zip-file-id"
    mock_get_store.return_value = mock_store

    zip_bytes = _create_test_zip()
    upload = _make_upload_file(zip_bytes, "site_export.zip", "application/zip")

    result = upload_files([upload], FileOrigin.CONNECTOR, unzip=False)

    # Should store exactly one file (the zip itself)
    assert len(result.file_paths) == 1
    assert result.file_paths[0] == "zip-file-id"
    assert result.file_names == ["site_export.zip"]
    # No zip metadata should be created
    assert result.zip_metadata_file_id is None

    # Verify the stored content is a valid zip
    saved_content: io.BytesIO = mock_store.save_file.call_args[1]["content"]
    saved_content.seek(0)
    with zipfile.ZipFile(saved_content, "r") as zf:
        assert set(zf.namelist()) == {"file1.txt", "file2.txt"}


@patch("onyx.server.documents.connector.get_default_file_store")
def test_upload_invalid_zip_with_unzip_false_raises(
    mock_get_store: MagicMock,
) -> None:
    """An invalid zip is rejected even when unzip=False (validation still runs)."""
    mock_get_store.return_value = MagicMock()

    bad_zip = _make_upload_file(b"not a zip", "bad.zip", "application/zip")

    with pytest.raises(BadZipFile):
        upload_files([bad_zip], FileOrigin.CONNECTOR, unzip=False)


@patch("onyx.server.documents.connector.get_default_file_store")
def test_upload_multiple_zips_rejected_when_unzip_false(
    mock_get_store: MagicMock,
) -> None:
    """The seen_zip guard rejects a second zip even when unzip=False."""
    mock_store = MagicMock()
    mock_store.save_file.return_value = "zip-id"
    mock_get_store.return_value = mock_store

    zip_bytes = _create_test_zip()
    zip1 = _make_upload_file(zip_bytes, "a.zip", "application/zip")
    zip2 = _make_upload_file(zip_bytes, "b.zip", "application/zip")

    with pytest.raises(Exception, match="Only one zip file"):
        upload_files([zip1, zip2], FileOrigin.CONNECTOR, unzip=False)


@patch("onyx.server.documents.connector.MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES", 1024)
@patch("onyx.server.documents.connector.get_default_file_store")
def test_upload_zip_rejected_when_uncompressed_size_exceeds_limit(
    mock_get_store: MagicMock,
) -> None:
    """An archive whose streamed uncompressed bytes exceed the configured
    limit must be rejected before any per-entry data is forwarded to the
    file store."""
    mock_store = MagicMock()
    mock_get_store.return_value = mock_store

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("payload.bin", b"\0" * 4096)
    upload = _make_upload_file(buf.getvalue(), "big.zip", "application/zip")

    with pytest.raises(OnyxError) as exc_info:
        upload_files([upload], FileOrigin.CONNECTOR)

    assert exc_info.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE
    mock_store.save_file.assert_not_called()


@patch("onyx.server.documents.connector.MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES", 1024)
@patch("onyx.server.documents.connector.get_default_file_store")
def test_upload_zip_rolls_back_partial_writes_on_overflow(
    mock_get_store: MagicMock,
) -> None:
    """If a later entry trips the size cap, blobs that were already
    persisted during this archive's extraction must be deleted so the
    rejected request does not leak storage."""
    mock_store = MagicMock()
    mock_store.save_file.side_effect = ["id-small.txt"]
    mock_get_store.return_value = mock_store

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("small.txt", b"hi")
        zf.writestr("big.bin", b"\0" * 4096)
    upload = _make_upload_file(buf.getvalue(), "mixed.zip", "application/zip")

    with pytest.raises(OnyxError) as exc_info:
        upload_files([upload], FileOrigin.CONNECTOR)

    assert exc_info.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE
    # Only the small file was saved before overflow; verify it was
    # rolled back rather than leaked.
    assert mock_store.save_file.call_count == 1
    mock_store.delete_file.assert_called_once_with(
        "id-small.txt", error_on_missing=False
    )
