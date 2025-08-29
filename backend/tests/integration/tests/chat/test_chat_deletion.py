import pytest

from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


MESSAGE = "Hi"


@pytest.fixture(scope="module", autouse=True)
def reset_for_module() -> None:
    """Reset all data once before running any tests in this module."""
    reset_all()


@pytest.fixture
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    return LLMProviderManager.create(user_performing_action=admin_user)


def test_soft_delete_chat_session(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test soft deletion of a chat session.
    Soft delete should mark the chat as deleted but keep it in the database.
    """
    # Create a chat session
    test_chat_session = ChatSessionManager.create(
        persona_id=0,  # Use default persona
        description="Test chat session for soft deletion",
        user_performing_action=basic_user,
    )

    # Send a message to create some data
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message=MESSAGE,
        user_performing_action=basic_user,
    )

    # Verify that the message was processed successfully
    assert len(response.full_message) > 0, "Chat response should not be empty"

    # Verify that the chat session can be retrieved before deletion
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )
    assert len(chat_history) > 0, "Chat session should have messages"

    # Test soft deletion of the chat session
    deletion_success = ChatSessionManager.soft_delete(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )

    # Verify that the deletion was successful
    assert deletion_success, "Chat session soft deletion should succeed"

    # Verify that the chat session is soft deleted (marked as deleted but still in DB)
    assert ChatSessionManager.verify_soft_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Chat session should be soft deleted"

    # Verify that normal access is blocked
    assert ChatSessionManager.verify_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Chat session should not be accessible normally after soft delete"


def test_hard_delete_chat_session(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test hard deletion of a chat session.
    Hard delete should completely remove the chat from the database.
    """
    # Create a chat session
    test_chat_session = ChatSessionManager.create(
        persona_id=0,  # Use default persona
        description="Test chat session for hard deletion",
        user_performing_action=basic_user,
    )

    # Send a message to create some data
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message=MESSAGE,
        user_performing_action=basic_user,
    )

    # Verify that the message was processed successfully
    assert len(response.full_message) > 0, "Chat response should not be empty"

    # Verify that the chat session can be retrieved before deletion
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )
    assert len(chat_history) > 0, "Chat session should have messages"

    # Test hard deletion of the chat session
    deletion_success = ChatSessionManager.hard_delete(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )

    # Verify that the deletion was successful
    assert deletion_success, "Chat session hard deletion should succeed"

    # Verify that the chat session is hard deleted (completely removed from DB)
    assert ChatSessionManager.verify_hard_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Chat session should be hard deleted"

    # Verify that the chat session is not accessible at all
    assert ChatSessionManager.verify_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Chat session should not be accessible after hard delete"

    # Verify it's not soft deleted (since it doesn't exist at all)
    assert not ChatSessionManager.verify_soft_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Hard deleted chat should not be found as soft deleted"


def test_soft_delete_with_agentic_search(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test soft deletion of a chat session with agent behavior (sub-questions and sub-queries).
    Verifies that soft delete preserves all related agent records in the database.
    """
    # Create a chat session
    test_chat_session = ChatSessionManager.create(
        persona_id=0,
        description="Test agentic search soft deletion",
        user_performing_action=basic_user,
    )

    # Send a message using ChatSessionManager with agentic search enabled
    # This will create AgentSubQuestion and AgentSubQuery records
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="What are the key principles of software engineering?",
        user_performing_action=basic_user,
        use_agentic_search=True,
    )

    # Verify that the message was processed successfully
    assert len(response.full_message) > 0, "Chat response should not be empty"

    # Test soft deletion
    deletion_success = ChatSessionManager.soft_delete(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )

    # Verify successful soft deletion
    assert deletion_success, "Chat soft deletion should succeed"

    # Verify chat session is soft deleted
    assert ChatSessionManager.verify_soft_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Soft deleted chat session should be marked as deleted in DB"

    # Verify chat session is not accessible normally
    assert ChatSessionManager.verify_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Soft deleted chat session should not be accessible"


def test_hard_delete_with_agentic_search(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test hard deletion of a chat session with agent behavior (sub-questions and sub-queries).
    Verifies that hard delete removes all related agent records from the database via CASCADE.
    """
    # Create a chat session
    test_chat_session = ChatSessionManager.create(
        persona_id=0,
        description="Test agentic search hard deletion",
        user_performing_action=basic_user,
    )

    # Send a message using ChatSessionManager with agentic search enabled
    # This will create AgentSubQuestion and AgentSubQuery records
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="What are the key principles of software engineering?",
        user_performing_action=basic_user,
        use_agentic_search=True,
    )

    # Verify that the message was processed successfully
    assert len(response.full_message) > 0, "Chat response should not be empty"

    # Test hard deletion
    deletion_success = ChatSessionManager.hard_delete(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )

    # Verify successful hard deletion
    assert deletion_success, "Chat hard deletion should succeed"

    # Verify chat session is hard deleted (completely removed)
    assert ChatSessionManager.verify_hard_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Hard deleted chat session should be completely removed from DB"

    # Verify chat session is not accessible
    assert ChatSessionManager.verify_deleted(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    ), "Hard deleted chat session should not be accessible"


def test_multiple_soft_deletions(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test multiple chat session soft deletions to ensure proper handling
    when there are multiple related records.
    """
    chat_sessions = []

    # Create multiple chat sessions with potential agent behavior
    for i in range(3):
        chat_session = ChatSessionManager.create(
            persona_id=0,
            description=f"Test chat session {i} for multi-soft-deletion",
            user_performing_action=basic_user,
        )

        # Send a message to create some data
        ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message=f"Tell me about topic {i} with detailed analysis",
            user_performing_action=basic_user,
        )

        chat_sessions.append(chat_session)

    # Soft delete all chat sessions
    for chat_session in chat_sessions:
        deletion_success = ChatSessionManager.soft_delete(
            chat_session=chat_session,
            user_performing_action=basic_user,
        )
        assert deletion_success, f"Failed to soft delete chat {chat_session.id}"

    # Verify all chat sessions are soft deleted
    for chat_session in chat_sessions:
        assert ChatSessionManager.verify_soft_deleted(
            chat_session=chat_session,
            user_performing_action=basic_user,
        ), f"Chat {chat_session.id} should be soft deleted"

        assert ChatSessionManager.verify_deleted(
            chat_session=chat_session,
            user_performing_action=basic_user,
        ), f"Chat {chat_session.id} should not be accessible normally"


def test_multiple_hard_deletions_with_agent_data(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test multiple chat session hard deletions to ensure CASCADE deletes work correctly
    when there are multiple related records.
    """
    chat_sessions = []

    # Create multiple chat sessions with potential agent behavior
    for i in range(3):
        chat_session = ChatSessionManager.create(
            persona_id=0,
            description=f"Test chat session {i} for multi-hard-deletion",
            user_performing_action=basic_user,
        )

        # Send a message to create some data
        ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message=f"Tell me about topic {i} with detailed analysis",
            user_performing_action=basic_user,
        )

        chat_sessions.append(chat_session)

    # Hard delete all chat sessions
    for chat_session in chat_sessions:
        deletion_success = ChatSessionManager.hard_delete(
            chat_session=chat_session,
            user_performing_action=basic_user,
        )
        assert deletion_success, f"Failed to hard delete chat {chat_session.id}"

    # Verify all chat sessions are hard deleted
    for chat_session in chat_sessions:
        assert ChatSessionManager.verify_hard_deleted(
            chat_session=chat_session,
            user_performing_action=basic_user,
        ), f"Chat {chat_session.id} should be hard deleted"

        assert ChatSessionManager.verify_deleted(
            chat_session=chat_session,
            user_performing_action=basic_user,
        ), f"Chat {chat_session.id} should not be accessible"


def test_soft_vs_hard_delete_edge_cases(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test edge cases for both soft and hard deletion to ensure robustness.
    """
    # Test 1: Soft delete a chat session with no messages
    empty_chat_session_soft = ChatSessionManager.create(
        persona_id=0,
        description="Empty chat session for soft delete",
        user_performing_action=basic_user,
    )

    # Soft delete without sending any messages
    deletion_success = ChatSessionManager.soft_delete(
        chat_session=empty_chat_session_soft,
        user_performing_action=basic_user,
    )
    assert deletion_success, "Empty chat session should be soft deletable"
    assert ChatSessionManager.verify_soft_deleted(
        chat_session=empty_chat_session_soft,
        user_performing_action=basic_user,
    ), "Empty chat session should be confirmed as soft deleted"

    # Test 2: Hard delete a chat session with no messages
    empty_chat_session_hard = ChatSessionManager.create(
        persona_id=0,
        description="Empty chat session for hard delete",
        user_performing_action=basic_user,
    )

    # Hard delete without sending any messages
    deletion_success = ChatSessionManager.hard_delete(
        chat_session=empty_chat_session_hard,
        user_performing_action=basic_user,
    )
    assert deletion_success, "Empty chat session should be hard deletable"
    assert ChatSessionManager.verify_hard_deleted(
        chat_session=empty_chat_session_hard,
        user_performing_action=basic_user,
    ), "Empty chat session should be confirmed as hard deleted"

    # Test 3: Soft delete a chat session with multiple messages
    multi_message_chat_soft = ChatSessionManager.create(
        persona_id=0,
        description="Multi-message chat session for soft delete",
        user_performing_action=basic_user,
    )

    # Send multiple messages to create more complex data
    for i in range(3):
        ChatSessionManager.send_message(
            chat_session_id=multi_message_chat_soft.id,
            message=f"Message {i}: Tell me about different aspects of this topic",
            user_performing_action=basic_user,
        )

    # Verify messages exist
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=multi_message_chat_soft,
        user_performing_action=basic_user,
    )
    assert len(chat_history) >= 3, "Chat should have multiple messages"

    # Soft delete the chat with multiple messages
    deletion_success = ChatSessionManager.soft_delete(
        chat_session=multi_message_chat_soft,
        user_performing_action=basic_user,
    )
    assert deletion_success, "Multi-message chat session should be soft deletable"
    assert ChatSessionManager.verify_soft_deleted(
        chat_session=multi_message_chat_soft,
        user_performing_action=basic_user,
    ), "Multi-message chat session should be confirmed as soft deleted"

    # Test 4: Hard delete a chat session with multiple messages
    multi_message_chat_hard = ChatSessionManager.create(
        persona_id=0,
        description="Multi-message chat session for hard delete",
        user_performing_action=basic_user,
    )

    # Send multiple messages to create more complex data
    for i in range(3):
        ChatSessionManager.send_message(
            chat_session_id=multi_message_chat_hard.id,
            message=f"Message {i}: Tell me about different aspects of this topic",
            user_performing_action=basic_user,
        )

    # Verify messages exist
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=multi_message_chat_hard,
        user_performing_action=basic_user,
    )
    assert len(chat_history) >= 3, "Chat should have multiple messages"

    # Hard delete the chat with multiple messages
    deletion_success = ChatSessionManager.hard_delete(
        chat_session=multi_message_chat_hard,
        user_performing_action=basic_user,
    )
    assert deletion_success, "Multi-message chat session should be hard deletable"
    assert ChatSessionManager.verify_hard_deleted(
        chat_session=multi_message_chat_hard,
        user_performing_action=basic_user,
    ), "Multi-message chat session should be confirmed as hard deleted"
