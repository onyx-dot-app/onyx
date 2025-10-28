from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestUser


def test_send_two_messages(basic_user: DATestUser) -> None:
    # Create a chat session
    test_chat_session = ChatSessionManager.create(
        persona_id=0,  # Use default persona
        description="Test chat session for soft deletion",
        user_performing_action=basic_user,
    )

    # Send a message to create some data
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="hello",
        user_performing_action=basic_user,
    )
    # Verify that the message was processed successfully
    assert response.error is None, "Chat response should not have an error"
    assert len(response.full_message) > 0, "Chat response should not be empty"

    # Verify that the chat session can be retrieved before deletion
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )
    assert (
        len(chat_history) == 3
    ), "Chat session should have 1 system message, 1 user message, and 1 assistant message"

    response2 = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="hello again",
        user_performing_action=basic_user,
        parent_message_id=response.assistant_message_id,
    )
    print(response2.error)
    assert response2.error is None, "Chat response should not have an error"
    assert len(response2.full_message) > 0, "Chat response should not be empty"

    # Verify that the chat session can be retrieved before deletion
    chat_history2 = ChatSessionManager.get_chat_history(
        chat_session=test_chat_session,
        user_performing_action=basic_user,
    )
    assert (
        len(chat_history2) == 5
    ), "Chat session should have 1 system message, 2 user messages, and 2 assistant messages"
