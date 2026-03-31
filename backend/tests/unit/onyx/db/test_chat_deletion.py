"""Tests for chat session and message deletion resilience."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.db.chat import delete_messages_and_files_from_chat_session


@patch("onyx.db.chat.delete_orphaned_search_docs")
@patch("onyx.db.chat.get_default_file_store")
def test_delete_messages_skips_missing_files(
    mock_get_file_store: MagicMock,
    _mock_delete_orphaned: Any,
) -> None:
    """Deletion should continue when a referenced file record no longer exists."""
    session_id = uuid4()

    file_store = MagicMock()
    file_store.delete_file.side_effect = [
        None,  # first file deletes fine
        RuntimeError("File by id abc does not exist or was deleted"),
        None,  # third file deletes fine
    ]
    mock_get_file_store.return_value = file_store

    mock_db_session = MagicMock()
    mock_db_session.execute.return_value.fetchall.return_value = [
        (1, [{"id": "file-ok-1"}, {"id": "file-missing"}, {"id": "file-ok-2"}]),
    ]

    delete_messages_and_files_from_chat_session(session_id, mock_db_session)

    assert file_store.delete_file.call_count == 3
    mock_db_session.execute.assert_called()
    mock_db_session.commit.assert_called()


@patch("onyx.db.chat.delete_orphaned_search_docs")
@patch("onyx.db.chat.get_default_file_store")
def test_delete_messages_succeeds_with_no_files(
    mock_get_file_store: MagicMock,
    _mock_delete_orphaned: Any,
) -> None:
    """Deletion works when messages have no attached files."""
    session_id = uuid4()

    mock_db_session = MagicMock()
    mock_db_session.execute.return_value.fetchall.return_value = [
        (1, None),
        (2, []),
    ]

    delete_messages_and_files_from_chat_session(session_id, mock_db_session)

    mock_get_file_store.return_value.delete_file.assert_not_called()
    mock_db_session.commit.assert_called()
