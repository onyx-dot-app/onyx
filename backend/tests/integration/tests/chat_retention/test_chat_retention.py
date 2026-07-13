import os
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import UUID

import httpx
import pytest
from pytest import MonkeyPatch
from sqlalchemy import update
from sqlalchemy.orm import Session

import ee.onyx.background.celery.tasks.ttl_management.tasks as ttl_tasks
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from shared_configs.contextvars import get_current_tenant_id
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser

RETENTION_SECONDS = 10


def _run_ttl_cleanup(retention_days: int) -> None:
    """Directly execute TTL cleanup logic, bypassing Celery task infrastructure."""
    with get_session_with_current_tenant() as db_session:
        old_chat_sessions = get_chat_sessions_older_than(retention_days, db_session)

    for user_id, session_id in old_chat_sessions:
        with get_session_with_current_tenant() as db_session:
            delete_chat_session(
                user_id,
                session_id,
                db_session,
                include_deleted=True,
                hard_delete=True,
            )


def _backdate_session(
    session_id: UUID, created_days_ago: int, last_message_days_ago: int
) -> None:
    """Rewrite a session's creation time and its messages' sent time so retention
    behavior can be tested deterministically without sleeping."""
    now = datetime.now(tz=timezone.utc)
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(time_created=now - timedelta(days=created_days_ago))
        )
        db_session.execute(
            update(ChatMessage)
            .where(ChatMessage.chat_session_id == session_id)
            .values(time_sent=now - timedelta(days=last_message_days_ago))
        )
        db_session.commit()


def _is_session_deleted(chat_session: DATestChatSession, user: DATestUser) -> bool:
    try:
        history = ChatSessionManager.get_chat_history(
            chat_session=chat_session,
            user_performing_action=user,
        )
        return len(history) == 0
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 400):
            return True
        raise


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_chat_retention(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Test that chat sessions are deleted after the retention period expires."""

    retention_days = RETENTION_SECONDS // 86400
    settings = DATestSettings(maximum_chat_retention_days=retention_days)
    SettingsManager.update_settings(settings, user_performing_action=admin_user)

    chat_session = ChatSessionManager.create(
        persona_id=0,
        description="Test chat retention",
        user_performing_action=admin_user,
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="This message should be deleted soon",
        user_performing_action=admin_user,
    )
    assert response.error is None, (
        f"Chat response should not have an error: {response.error}"
    )

    chat_history = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )
    assert len(chat_history) > 0, "Chat session should have messages"

    # Wait for the retention period to elapse, then directly run TTL cleanup
    time.sleep(RETENTION_SECONDS + 2)
    _run_ttl_cleanup(retention_days)

    # Verify the chat session was deleted
    assert _is_session_deleted(chat_session, admin_user), (
        "Chat session was not deleted after retention period"
    )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_chat_retention_uses_last_message_time(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Retention is based on last message time, not session creation time.

    An old session that received a recent message should be retained, while an
    old session with no recent activity should be deleted.
    """

    retention_days = 30
    settings = DATestSettings(maximum_chat_retention_days=retention_days)
    SettingsManager.update_settings(settings, user_performing_action=admin_user)

    # Created long ago but recently used -> should be RETAINED
    active_session = ChatSessionManager.create(
        persona_id=0,
        description="Old session, recent activity",
        user_performing_action=admin_user,
    )
    active_response = ChatSessionManager.send_message(
        chat_session_id=active_session.id,
        message="Recent message keeps this session alive",
        user_performing_action=admin_user,
    )
    assert active_response.error is None, (
        f"Chat response should not have an error: {active_response.error}"
    )
    _backdate_session(active_session.id, created_days_ago=60, last_message_days_ago=1)

    # Created long ago and inactive -> should be DELETED
    stale_session = ChatSessionManager.create(
        persona_id=0,
        description="Old session, no recent activity",
        user_performing_action=admin_user,
    )
    stale_response = ChatSessionManager.send_message(
        chat_session_id=stale_session.id,
        message="This session has gone stale",
        user_performing_action=admin_user,
    )
    assert stale_response.error is None, (
        f"Chat response should not have an error: {stale_response.error}"
    )
    _backdate_session(stale_session.id, created_days_ago=60, last_message_days_ago=60)

    _run_ttl_cleanup(retention_days)

    assert not _is_session_deleted(active_session, admin_user), (
        "Session with a recent message should be retained"
    )
    assert _is_session_deleted(stale_session, admin_user), (
        "Session with no recent activity should be deleted"
    )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_chat_retention_batched_deletion(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    monkeypatch: MonkeyPatch,
) -> None:
    """The real TTL task drains a backlog spanning multiple batches.

    Forces a small batch size so several sessions require more than one batch,
    then runs the actual Celery task to verify the drain loop deletes every old
    session and terminates.
    """

    retention_days = 30
    settings = DATestSettings(maximum_chat_retention_days=retention_days)
    SettingsManager.update_settings(settings, user_performing_action=admin_user)

    monkeypatch.setattr(ttl_tasks, "_TTL_DELETE_BATCH_SIZE", 2)

    old_sessions: list[DATestChatSession] = []
    for i in range(5):
        session = ChatSessionManager.create(
            persona_id=0,
            description=f"Stale session {i}",
            user_performing_action=admin_user,
        )
        response = ChatSessionManager.send_message(
            chat_session_id=session.id,
            message="This session should be cleaned up",
            user_performing_action=admin_user,
        )
        assert response.error is None, (
            f"Chat response should not have an error: {response.error}"
        )
        _backdate_session(session.id, created_days_ago=60, last_message_days_ago=60)
        old_sessions.append(session)

    # Run the real task (eager) so the batched drain loop + Redis lock execute.
    result = ttl_tasks.perform_ttl_management_task.apply(
        kwargs=dict(
            retention_limit_days=retention_days,
            tenant_id=get_current_tenant_id(),
        ),
    )
    assert result.successful(), f"TTL task failed: {result.traceback}"

    for session in old_sessions:
        assert _is_session_deleted(session, admin_user), (
            f"Session {session.id} should have been deleted by batched cleanup"
        )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_chat_retention_skips_failing_session(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    monkeypatch: MonkeyPatch,
) -> None:
    """A single undeletable session must not block the rest of the backlog.

    The oldest session is made to fail deletion. Because cleanup runs oldest
    first, a naive stop-on-no-progress guard would strand every newer session
    behind it. The failed session should be skipped and all others deleted.
    """

    retention_days = 30
    settings = DATestSettings(maximum_chat_retention_days=retention_days)
    SettingsManager.update_settings(settings, user_performing_action=admin_user)

    monkeypatch.setattr(ttl_tasks, "_TTL_DELETE_BATCH_SIZE", 2)

    # Oldest session (largest last_message_days_ago) is fetched first.
    poison_session = ChatSessionManager.create(
        persona_id=0,
        description="Undeletable oldest session",
        user_performing_action=admin_user,
    )
    poison_response = ChatSessionManager.send_message(
        chat_session_id=poison_session.id,
        message="This session's deletion will fail",
        user_performing_action=admin_user,
    )
    assert poison_response.error is None
    _backdate_session(poison_session.id, created_days_ago=90, last_message_days_ago=90)

    deletable_sessions: list[DATestChatSession] = []
    for i in range(4):
        session = ChatSessionManager.create(
            persona_id=0,
            description=f"Deletable session {i}",
            user_performing_action=admin_user,
        )
        response = ChatSessionManager.send_message(
            chat_session_id=session.id,
            message="This session should be cleaned up",
            user_performing_action=admin_user,
        )
        assert response.error is None
        _backdate_session(session.id, created_days_ago=60, last_message_days_ago=60)
        deletable_sessions.append(session)

    real_delete_chat_session = ttl_tasks.delete_chat_session

    def _delete_or_fail(
        user_id: UUID | None,
        chat_session_id: UUID,
        db_session: Session,
        include_deleted: bool = False,
        hard_delete: bool = False,
    ) -> None:
        if str(chat_session_id) == str(poison_session.id):
            raise RuntimeError("Simulated delete failure")
        real_delete_chat_session(
            user_id,
            chat_session_id,
            db_session,
            include_deleted=include_deleted,
            hard_delete=hard_delete,
        )

    monkeypatch.setattr(ttl_tasks, "delete_chat_session", _delete_or_fail)

    result = ttl_tasks.perform_ttl_management_task.apply(
        kwargs=dict(
            retention_limit_days=retention_days,
            tenant_id=get_current_tenant_id(),
        ),
    )
    assert result.successful(), f"TTL task failed: {result.traceback}"

    assert not _is_session_deleted(poison_session, admin_user), (
        "The failing session should remain (retried on the next run)"
    )
    for session in deletable_sessions:
        assert _is_session_deleted(session, admin_user), (
            f"Session {session.id} should be deleted despite an older failing session"
        )
