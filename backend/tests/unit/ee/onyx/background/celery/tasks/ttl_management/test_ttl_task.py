"""Tests for TTL management task resilience."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4


_TASK_MODULE = "ee.onyx.background.celery.tasks.ttl_management.tasks"


def _setup_db_session_mock(mock_get_db_session: MagicMock) -> None:
    mock_db_session = MagicMock()
    mock_get_db_session.return_value.__enter__ = MagicMock(
        return_value=mock_db_session
    )
    mock_get_db_session.return_value.__exit__ = MagicMock(return_value=False)


@patch(f"{_TASK_MODULE}.get_session_with_current_tenant")
@patch(f"{_TASK_MODULE}.delete_chat_session")
@patch(f"{_TASK_MODULE}.get_chat_sessions_older_than")
@patch(f"{_TASK_MODULE}.mark_task_as_finished_with_id")
@patch(f"{_TASK_MODULE}.register_task")
def test_ttl_task_continues_after_session_delete_failure(
    _mock_register: Any,
    mock_mark_finished: MagicMock,
    mock_get_old_sessions: MagicMock,
    mock_delete_session: MagicMock,
    mock_get_db_session: MagicMock,
) -> None:
    """One failing session should not prevent cleanup of remaining sessions."""
    from ee.onyx.background.celery.tasks.ttl_management.tasks import (
        perform_ttl_management_task,
    )

    user1, session1 = uuid4(), uuid4()
    user2, session2 = uuid4(), uuid4()
    user3, session3 = uuid4(), uuid4()

    mock_get_old_sessions.return_value = [
        (user1, session1),
        (user2, session2),
        (user3, session3),
    ]

    # Second session fails
    mock_delete_session.side_effect = [
        None,
        RuntimeError("File does not exist"),
        None,
    ]

    _setup_db_session_mock(mock_get_db_session)

    mock_task = MagicMock()
    mock_task.request.id = "test-task-id"

    # Call the underlying function directly, bypassing Celery decorator
    perform_ttl_management_task.__wrapped__(
        mock_task, retention_limit_days=30, tenant_id="test"
    )

    # All three sessions should have been attempted
    assert mock_delete_session.call_count == 3

    # Task marked as finished with success=False (due to the one failure)
    mock_mark_finished.assert_called()
    finish_call_kwargs = mock_mark_finished.call_args[1]
    assert finish_call_kwargs["success"] is False


@patch(f"{_TASK_MODULE}.get_session_with_current_tenant")
@patch(f"{_TASK_MODULE}.delete_chat_session")
@patch(f"{_TASK_MODULE}.get_chat_sessions_older_than")
@patch(f"{_TASK_MODULE}.mark_task_as_finished_with_id")
@patch(f"{_TASK_MODULE}.register_task")
def test_ttl_task_reports_success_when_all_deletions_pass(
    _mock_register: Any,
    mock_mark_finished: MagicMock,
    mock_get_old_sessions: MagicMock,
    mock_delete_session: MagicMock,
    mock_get_db_session: MagicMock,
) -> None:
    """Task should report success when all sessions are deleted."""
    from ee.onyx.background.celery.tasks.ttl_management.tasks import (
        perform_ttl_management_task,
    )

    mock_get_old_sessions.return_value = [
        (uuid4(), uuid4()),
        (uuid4(), uuid4()),
    ]
    mock_delete_session.side_effect = None

    _setup_db_session_mock(mock_get_db_session)

    mock_task = MagicMock()
    mock_task.request.id = "test-task-id"

    perform_ttl_management_task.__wrapped__(
        mock_task, retention_limit_days=30, tenant_id="test"
    )

    assert mock_delete_session.call_count == 2

    mock_mark_finished.assert_called()
    finish_call_kwargs = mock_mark_finished.call_args[1]
    assert finish_call_kwargs["success"] is True
