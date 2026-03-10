import os
import time

import pytest
import requests

from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.settings import SettingsManager
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


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_chat_retention(
    reset: None, admin_user: DATestUser, llm_provider: DATestLLMProvider  # noqa: ARG001
) -> None:  # noqa: ARG001
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
    assert (
        response.error is None
    ), f"Chat response should not have an error: {response.error}"

    chat_history = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )
    assert len(chat_history) > 0, "Chat session should have messages"

    # Wait for the retention period to elapse, then directly run TTL cleanup
    time.sleep(RETENTION_SECONDS + 2)
    _run_ttl_cleanup(retention_days)

    # Verify the chat session was deleted
    session_deleted = False
    try:
        chat_history = ChatSessionManager.get_chat_history(
            chat_session=chat_session,
            user_performing_action=admin_user,
        )
        session_deleted = len(chat_history) == 0
    except requests.exceptions.HTTPError as e:
        if e.response.status_code in (404, 400):
            session_deleted = True
        else:
            raise

    assert session_deleted, "Chat session was not deleted after retention period"
