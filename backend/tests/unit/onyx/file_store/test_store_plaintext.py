"""Tests for store_plaintext caching behavior in file_store.utils."""

from io import BytesIO
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.file_store.models import ChatFileType
from onyx.file_store.utils import load_user_file
from onyx.file_store.utils import store_plaintext

_UTILS_MODULE = "onyx.file_store.utils"


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_store_plaintext_persists_non_empty_content(
    mock_get_file_store: MagicMock,
) -> None:
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    assert store_plaintext("file-1", "hello world") is True

    file_store.save_file.assert_called_once()
    assert file_store.save_file.call_args.kwargs["file_id"] == "plaintext_file-1"


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_store_plaintext_persists_empty_content(
    mock_get_file_store: MagicMock,
) -> None:
    """Empty content must be cached too: it marks unprocessable files
    (e.g. .zip) so subsequent chat turns don't re-fetch and re-attempt
    extraction. See _get_or_extract_plaintext in onyx/chat/chat_utils.py.
    """
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    assert store_plaintext("file-2", "") is True

    file_store.save_file.assert_called_once()
    assert file_store.save_file.call_args.kwargs["file_id"] == "plaintext_file-2"


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_store_plaintext_returns_false_on_save_failure(
    mock_get_file_store: MagicMock,
) -> None:
    file_store = MagicMock()
    file_store.save_file.side_effect = RuntimeError("boom")
    mock_get_file_store.return_value = file_store

    assert store_plaintext("file-3", "data") is False


def _build_load_user_file_mocks(
    *,
    plaintext_bytes: bytes,
    original_bytes: bytes,
    file_mime: str = "application/zip",
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Shared setup for load_user_file tests.

    Returns (file_store, db_session, user_file) so individual tests can adjust
    side effects.  The file_store is wired so the first read_file call returns
    the plaintext bytes and the second returns the original bytes.
    """
    user_file_id = uuid4()
    user_file = MagicMock()
    user_file.id = user_file_id
    user_file.file_id = f"original-{user_file_id}"
    user_file.name = "thing.zip"

    db_session = MagicMock()
    db_session.query.return_value.filter.return_value.first.return_value = user_file

    file_record = MagicMock()
    file_record.file_type = file_mime
    file_record.display_name = "thing.zip"

    file_store = MagicMock()
    file_store.read_file_record.return_value = file_record
    file_store.read_file.side_effect = [
        BytesIO(plaintext_bytes),
        BytesIO(original_bytes),
    ]

    return file_store, db_session, user_file


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_load_user_file_empty_plaintext_falls_back_to_original_bytes(
    mock_get_file_store: MagicMock,
) -> None:
    """An empty plaintext cache entry (written for unprocessable files like
    .zip) must NOT be returned to downstream tools.  load_user_file should
    fall through to the original-bytes path so code interpreter and file
    reader still receive the real file content.
    """
    # Use an image mime type so the fallback path's chat_file_type is
    # distinguishable from PLAIN_TEXT (the type that would be set on the
    # cache-hit branch).  This makes the regression observable in both
    # `content` AND `file_type`.
    file_store, db_session, user_file = _build_load_user_file_mocks(
        plaintext_bytes=b"",
        original_bytes=b"\x89PNG\r\n\x1a\n-fake-png",
        file_mime="image/png",
    )
    mock_get_file_store.return_value = file_store

    chat_file = load_user_file(user_file.id, db_session)

    assert chat_file.content == b"\x89PNG\r\n\x1a\n-fake-png"
    # Original chat file type is preserved on fallback.
    assert chat_file.file_type == ChatFileType.IMAGE


@patch(f"{_UTILS_MODULE}.get_default_file_store")
def test_load_user_file_non_empty_plaintext_used_as_is(
    mock_get_file_store: MagicMock,
) -> None:
    file_store, db_session, user_file = _build_load_user_file_mocks(
        plaintext_bytes=b"extracted text",
        original_bytes=b"should-not-be-read",
        file_mime="application/pdf",
    )
    mock_get_file_store.return_value = file_store

    chat_file = load_user_file(user_file.id, db_session)

    assert chat_file.content == b"extracted text"
    assert chat_file.file_type == ChatFileType.PLAIN_TEXT
