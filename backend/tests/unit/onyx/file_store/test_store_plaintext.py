"""Tests for store_plaintext caching behavior in file_store.utils."""

from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.file_processing.extract_file_text import XLSX_TRUNCATION_MARKER
from onyx.file_store.models import ChatFileType, UserFileMetadata
from onyx.file_store.utils import (
    get_or_extract_artifact_text,
    get_or_extract_plaintext,
    load_user_file_content,
    store_plaintext,
)

_UTILS_MODULE = "onyx.file_store.utils"


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_store_plaintext_persists_non_empty_content(
    mock_get_file_store: MagicMock,
) -> None:
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    assert store_plaintext("plaintext_file-1", "hello world") is True

    file_store.save_file.assert_called_once()
    assert file_store.save_file.call_args.kwargs["file_id"] == "plaintext_file-1"


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_store_plaintext_persists_empty_content(
    mock_get_file_store: MagicMock,
) -> None:
    """Empty content must be cached too: it marks unprocessable files
    (e.g. .zip) so subsequent chat turns don't re-fetch and re-attempt
    extraction. See get_or_extract_plaintext.
    """
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    assert store_plaintext("plaintext_file-2", "") is True

    file_store.save_file.assert_called_once()
    assert file_store.save_file.call_args.kwargs["file_id"] == "plaintext_file-2"


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_store_plaintext_returns_false_on_save_failure(
    mock_get_file_store: MagicMock,
) -> None:
    file_store = MagicMock()
    file_store.save_file.side_effect = RuntimeError("boom")
    mock_get_file_store.return_value = file_store

    assert store_plaintext("plaintext_file-3", "data") is False


def _build_load_user_file_mocks(
    *,
    plaintext_bytes: bytes,
    original_bytes: bytes,
    file_mime: str = "application/zip",
) -> tuple[MagicMock, UserFileMetadata]:
    """Shared setup for file-content loading tests.

    Returns (file_store, user_file) so individual tests can adjust
    side effects.  The file_store is wired so the first read_file call returns
    the plaintext bytes and the second returns the original bytes.
    """
    user_file_id = uuid4()
    user_file = UserFileMetadata(
        id=user_file_id,
        file_id=f"original-{user_file_id}",
        name="thing.zip",
        file_type=file_mime,
        token_count=None,
    )

    file_record = MagicMock()
    file_record.file_type = file_mime
    file_record.display_name = "thing.zip"

    file_store = MagicMock()
    file_store.read_file_record.return_value = file_record
    file_store.read_file.side_effect = [
        BytesIO(plaintext_bytes),
        BytesIO(original_bytes),
    ]

    return file_store, user_file


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_load_user_file_empty_plaintext_falls_back_to_original_bytes(
    mock_get_file_store: MagicMock,
) -> None:
    """An empty plaintext cache entry (written for unprocessable files like
    .zip) must NOT be returned to downstream tools.  load_user_file_content should
    fall through to the original-bytes path so code interpreter and file
    reader still receive the real file content.
    """
    # Use an image mime type so the fallback path's chat_file_type is
    # distinguishable from PLAIN_TEXT (the type that would be set on the
    # cache-hit branch).  This makes the regression observable in both
    # `content` AND `file_type`.
    file_store, user_file = _build_load_user_file_mocks(
        plaintext_bytes=b"",
        original_bytes=b"\x89PNG\r\n\x1a\n-fake-png",
        file_mime="image/png",
    )
    mock_get_file_store.return_value = file_store

    chat_file = load_user_file_content(user_file)

    assert chat_file.content == b"\x89PNG\r\n\x1a\n-fake-png"
    # Original chat file type is preserved on fallback.
    assert chat_file.file_type == ChatFileType.IMAGE


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_load_user_file_non_empty_plaintext_used_as_is(
    mock_get_file_store: MagicMock,
) -> None:
    file_store, user_file = _build_load_user_file_mocks(
        plaintext_bytes=b"extracted text",
        original_bytes=b"should-not-be-read",
        file_mime="application/pdf",
    )
    mock_get_file_store.return_value = file_store

    chat_file = load_user_file_content(user_file)

    assert chat_file.content == b"extracted text"
    assert chat_file.file_type == ChatFileType.PLAIN_TEXT


class TestGetOrExtractPlaintext:
    """The text cache that chat file loading and published file text read."""

    def test_cache_hit_skips_extraction(self) -> None:
        file_store = MagicMock()
        file_store.read_file.return_value = BytesIO(b"cached text")
        extract_fn = MagicMock(return_value="should not be called")

        with (
            patch(
                f"{_UTILS_MODULE}.get_default_file_store",
                return_value=file_store,
            ),
            patch(f"{_UTILS_MODULE}.store_plaintext") as store_plaintext,
        ):
            result = get_or_extract_plaintext("plaintext_file-1", extract_fn)

        assert result == "cached text"
        extract_fn.assert_not_called()
        store_plaintext.assert_not_called()

    def test_cache_miss_stores_extracted_text(self) -> None:
        file_store = MagicMock()
        file_store.read_file.side_effect = RuntimeError("not in store")
        extract_fn = MagicMock(return_value="extracted text")

        with (
            patch(
                f"{_UTILS_MODULE}.get_default_file_store",
                return_value=file_store,
            ),
            patch(f"{_UTILS_MODULE}.store_plaintext") as store_plaintext,
        ):
            result = get_or_extract_plaintext("plaintext_file-2", extract_fn)

        assert result == "extracted text"
        extract_fn.assert_called_once()
        store_plaintext.assert_called_once_with("plaintext_file-2", "extracted text")

    def test_cache_miss_caches_empty_extraction(self) -> None:
        """Files extract_file_text cannot process (e.g. .zip) return "".
        We must still cache that result so we don't re-fetch the file from
        object storage on every subsequent chat turn.
        """
        file_store = MagicMock()
        file_store.read_file.side_effect = RuntimeError("not in store")
        extract_fn = MagicMock(return_value="")

        with (
            patch(
                f"{_UTILS_MODULE}.get_default_file_store",
                return_value=file_store,
            ),
            patch(f"{_UTILS_MODULE}.store_plaintext") as store_plaintext,
        ):
            result = get_or_extract_plaintext("plaintext_file-3", extract_fn)

        assert result == ""
        extract_fn.assert_called_once()
        store_plaintext.assert_called_once_with("plaintext_file-3", "")


def test_a_sheet_cut_at_the_cell_cap_is_truncated() -> None:
    file_store = MagicMock()
    file_store.read_file.return_value = BytesIO(
        f"a,b\n{XLSX_TRUNCATION_MARKER}\f".encode()
    )

    with patch(f"{_UTILS_MODULE}.get_default_file_store", return_value=file_store):
        text = get_or_extract_artifact_text("file-1", "big.xlsx", 10)

    assert text is not None
    assert text.truncated


def test_a_text_file_that_holds_the_sheet_marker_is_not_truncated() -> None:
    file_store = MagicMock()
    file_store.read_file.return_value = BytesIO(
        f"notes\n{XLSX_TRUNCATION_MARKER}".encode()
    )

    with patch(f"{_UTILS_MODULE}.get_default_file_store", return_value=file_store):
        text = get_or_extract_artifact_text("file-1", "notes.txt", 10)

    assert text is not None
    assert not text.truncated
