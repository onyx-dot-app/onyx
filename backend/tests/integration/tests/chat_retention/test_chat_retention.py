import os
import time
import uuid
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
from onyx.configs.constants import CELERY_CHAT_TTL_DELETE_TASK_EXPIRES
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.redis.redis_pool import get_redis_client
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


def _make_old_session(
    admin_user: DATestUser, description: str, days_old: int = 60
) -> DATestChatSession:
    """Create a chat session with a message, aged so TTL cleanup will select it."""
    session = ChatSessionManager.create(
        persona_id=0,
        description=description,
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
    _backdate_session(
        session.id, created_days_ago=days_old, last_message_days_ago=days_old
    )
    return session


def _run_perform_ttl(retention_days: int) -> None:
    """Claim the chain marker with a fresh token, then run one perform task.

    Mirrors how the beat starts a chain: perform only proceeds while it owns the
    marker, so the token must be claimed before invoking it.
    """
    tenant_id = get_current_tenant_id()
    token = uuid.uuid4().hex
    get_redis_client(tenant_id=tenant_id).set(
        OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE,
        token,
        ex=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
    )
    result = ttl_tasks.perform_ttl_management_task.apply(
        kwargs=dict(
            retention_limit_days=retention_days,
            chain_token=token,
            tenant_id=tenant_id,
        ),
    )
    assert result.successful(), f"TTL task failed: {result.traceback}"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_perform_ttl_deletes_oldest_expired(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """The worker hard-deletes the oldest batch of expired sessions."""

    retention_days = 30
    sessions = [_make_old_session(admin_user, f"Stale session {i}") for i in range(3)]

    _run_perform_ttl(retention_days)

    for session in sessions:
        assert _is_session_deleted(session, admin_user), (
            f"Session {session.id} should have been deleted by TTL cleanup"
        )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_perform_ttl_continues_past_failing_session(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    monkeypatch: MonkeyPatch,
) -> None:
    """One undeletable session must not block the rest of the batch.

    The worker logs and continues past a failing delete, so every other expired
    session is still removed and the task itself succeeds.
    """

    retention_days = 30
    poison_session = _make_old_session(admin_user, "Undeletable session")
    deletable_sessions = [
        _make_old_session(admin_user, f"Deletable session {i}") for i in range(3)
    ]

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

    _run_perform_ttl(retention_days)

    assert not _is_session_deleted(poison_session, admin_user), (
        "The failing session should remain (retried on the next run)"
    )
    for session in deletable_sessions:
        assert _is_session_deleted(session, admin_user), (
            f"Session {session.id} should be deleted despite a failing session"
        )
