"""Tests for store_plaintext caching behavior in file_store.utils."""

from unittest.mock import MagicMock
from unittest.mock import patch

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
