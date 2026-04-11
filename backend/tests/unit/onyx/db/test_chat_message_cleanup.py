"""Regression tests for delete_messages_and_files_from_chat_session.

Verifies that user-owned files (those with user_file_id) are never deleted
during chat session cleanup — only chat-only files should be removed.
"""

from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.db.chat import delete_messages_and_files_from_chat_session

_MODULE = "onyx.db.chat"


def _make_db_session(
    rows: list[tuple[int, list[dict[str, str]] | None]],
) -> MagicMock:
    db_session = MagicMock()
    db_session.execute.return_value.tuples.return_value.all.return_value = rows
    return db_session


@patch(f"{_MODULE}.delete_orphaned_search_docs")
@patch(f"{_MODULE}.get_default_file_store")
def test_user_files_are_not_deleted(
    mock_get_file_store: MagicMock,
    _mock_orphan_cleanup: MagicMock,
) -> None:
    """User files (with user_file_id) must be skipped during cleanup."""
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    db_session = _make_db_session(
        [
            (
                1,
                [
                    {"id": "chat-file-1", "type": "image"},
                    {"id": "user-file-1", "type": "document", "user_file_id": "uf-1"},
                    {"id": "chat-file-2", "type": "image"},
                ],
            ),
        ]
    )

    delete_messages_and_files_from_chat_session(uuid4(), db_session)

    assert file_store.delete_file.call_count == 2
    file_store.delete_file.assert_has_calls(
        [
            call(file_id="chat-file-1", error_on_missing=False),
            call(file_id="chat-file-2", error_on_missing=False),
        ]
    )


@patch(f"{_MODULE}.delete_orphaned_search_docs")
@patch(f"{_MODULE}.get_default_file_store")
def test_only_user_files_means_no_deletions(
    mock_get_file_store: MagicMock,
    _mock_orphan_cleanup: MagicMock,
) -> None:
    """When every file in the session is a user file, nothing should be deleted."""
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    db_session = _make_db_session(
        [
            (1, [{"id": "uf-a", "type": "document", "user_file_id": "uf-1"}]),
            (2, [{"id": "uf-b", "type": "document", "user_file_id": "uf-2"}]),
        ]
    )

    delete_messages_and_files_from_chat_session(uuid4(), db_session)

    file_store.delete_file.assert_not_called()


@patch(f"{_MODULE}.delete_orphaned_search_docs")
@patch(f"{_MODULE}.get_default_file_store")
def test_messages_with_no_files(
    mock_get_file_store: MagicMock,
    _mock_orphan_cleanup: MagicMock,
) -> None:
    """Messages with None or empty file lists should not trigger any deletions."""
    file_store = MagicMock()
    mock_get_file_store.return_value = file_store

    db_session = _make_db_session(
        [
            (1, None),
            (2, []),
        ]
    )

    delete_messages_and_files_from_chat_session(uuid4(), db_session)

    file_store.delete_file.assert_not_called()
