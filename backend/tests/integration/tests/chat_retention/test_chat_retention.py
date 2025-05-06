import os
import time

import pytest
import requests

from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat retention tests are enterprise only",
)
def test_chat_retention(reset: None, admin_user: DATestUser) -> None:
    """Test that chat sessions are deleted after the retention period expires."""

    # Set chat retention period to 10 seconds
    retention_days = 10 / 86400  # 10 seconds in days (10 / 24 / 60 / 60)
    settings = DATestSettings(maximum_chat_retention_days=retention_days)
    SettingsManager.update_settings(settings, user_performing_action=admin_user)

    # Create a chat session
    chat_session = ChatSessionManager.create(
        persona_id=0,
        description="Test chat retention",
        user_performing_action=admin_user,
    )

    # Send a message
    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="This message should be deleted soon",
        user_performing_action=admin_user,
    )

    # Verify the chat session exists
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )
    assert len(chat_history) > 0, "Chat session should have messages"

    # Wait for TTL task to run (give it ~60 seconds)
    print("Waiting for chat retention TTL task to run...")
    max_wait_time = 60  # maximum time to wait in seconds
    start_time = time.time()
    session_deleted = False

    while not session_deleted and (time.time() - start_time < max_wait_time):
        # Check if chat session is deleted
        try:
            # Attempt to get chat history - this should 404
            chat_history = ChatSessionManager.get_chat_history(
                chat_session=chat_session,
                user_performing_action=admin_user,
            )

            # If we got no messages or an empty response, session might be deleted
            if not chat_history:
                session_deleted = True
                break

        except requests.exceptions.HTTPError as e:
            # If we get a 404 or other error, the session is gone
            if e.response.status_code in (404, 400):
                session_deleted = True
                break
            raise  # Re-raise other errors

        # Wait a bit before checking again
        time.sleep(5)
        print(f"Waited {time.time() - start_time:.1f} seconds for chat deletion...")

    # Assert that the chat session was deleted
    assert session_deleted, "Chat session was not deleted within the expected time"
