import os
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import SessionType
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.query_history import QueryHistoryManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture
def setup_chat_session(reset: None) -> tuple[DATestUser, str]:
    # Create admin user and required resources
    admin_user: DATestUser = UserManager.create(name="admin_user")
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    LLMProviderManager.create(user_performing_action=admin_user)

    # Seed a document
    cc_pair.documents = []
    cc_pair.documents.append(
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair,
            content="The company's revenue in Q1 was $1M",
            api_key=api_key,
        )
    )

    # Create chat session and send a message
    chat_session = ChatSessionManager.create(
        persona_id=0,
        description="Test chat session",
        user_performing_action=admin_user,
    )

    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What was the Q1 revenue?",
        user_performing_action=admin_user,
    )

    messages = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )

    # Add another message to the chat session
    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What about Q2 revenue?",
        user_performing_action=admin_user,
        parent_message_id=messages[-1].id,
    )

    return admin_user, str(chat_session.id)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat history tests are enterprise only",
)
def test_chat_history_endpoints(
    reset: None, setup_chat_session: tuple[DATestUser, str]
) -> None:
    admin_user, first_chat_id = setup_chat_session

    # Get chat history
    history_response = QueryHistoryManager.get_query_history_page(
        user_performing_action=admin_user
    )

    # Verify we got back the one chat session we created
    assert len(history_response.items) == 1

    # Verify the first chat session details
    first_session = history_response.items[0]
    assert first_session.user_email == admin_user.email
    assert first_session.name == "Test chat session"
    assert first_session.first_user_message == "What was the Q1 revenue?"
    assert first_session.first_ai_message is not None
    assert first_session.assistant_id == 0
    assert first_session.feedback_type is None
    assert first_session.flow_type == SessionType.CHAT
    assert first_session.conversation_length == 4  # 2 User messages + 2 AI responses

    # Test date filtering - should return no results
    past_end = datetime.now(tz=timezone.utc) - timedelta(days=1)
    past_start = past_end - timedelta(days=1)
    history_response = QueryHistoryManager.get_query_history_page(
        start_time=past_start,
        end_time=past_end,
        user_performing_action=admin_user,
    )
    assert len(history_response.items) == 0

    # Test get specific chat session endpoint
    session_details = QueryHistoryManager.get_chat_session_admin(
        chat_session_id=first_chat_id,
        user_performing_action=admin_user,
    )

    # Verify the session details
    assert str(session_details.id) == first_chat_id
    assert len(session_details.messages) > 0
    assert session_details.flow_type == SessionType.CHAT

    # Test filtering by feedback
    history_response = QueryHistoryManager.get_query_history_page(
        feedback_type=QAFeedbackType.LIKE,
        user_performing_action=admin_user,
    )
    assert len(history_response.items) == 0


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Chat history tests are enterprise only",
)
def test_chat_history_csv_export(
    reset: None, setup_chat_session: tuple[DATestUser, str]
) -> None:
    admin_user, _ = setup_chat_session

    # Test CSV export endpoint with date filtering
    headers, csv_content = QueryHistoryManager.get_query_history_as_csv(
        user_performing_action=admin_user,
    )
    assert headers["Content-Type"] == "text/csv; charset=utf-8"
    assert "Content-Disposition" in headers

    # Verify CSV content
    csv_lines = csv_content.strip().split("\n")
    assert len(csv_lines) == 3  # Header + 2 QA pairs
    assert "chat_session_id" in csv_content
    assert "user_message" in csv_content
    assert "ai_response" in csv_content
    assert "What was the Q1 revenue?" in csv_content
    assert "What about Q2 revenue?" in csv_content

    # Test CSV export with date filtering - should return no results
    past_end = datetime.now(tz=timezone.utc) - timedelta(days=1)
    past_start = past_end - timedelta(days=1)
    headers, csv_content = QueryHistoryManager.get_query_history_as_csv(
        start_time=past_start,
        end_time=past_end,
        user_performing_action=admin_user,
    )
    csv_lines = csv_content.strip().split("\n")
    assert len(csv_lines) == 1  # Only header, no data rows
