import time

from onyx.configs.constants import MessageType
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.conftest import DocumentBuilderType

TERMINATED_RESPONSE_MESSAGE = (
    "Response was terminated prior to completion, try regenerating."
)


def test_send_two_messages(basic_user: DATestUser) -> None:
    # Create a chat session
    test_chat_session = ChatSessionManager.create(
        persona_id=0,  # Use default persona
        description="Test chat session for multiple messages",
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


def test_send_message_simple_with_history(reset: None, admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="this is a test message",
        user_performing_action=admin_user,
    )

    assert response.error is None, "Chat response should not have an error"
    assert len(response.full_message) > 0


def test_send_message__basic_searches(
    reset: None, admin_user: DATestUser, document_builder: DocumentBuilderType
) -> None:
    MESSAGE = "run a search for 'test'. Use the internal search tool."
    SHORT_DOC_CONTENT = "test"
    LONG_DOC_CONTENT = "blah blah blah blah" * 100

    LLMProviderManager.create(user_performing_action=admin_user)

    short_doc = document_builder([SHORT_DOC_CONTENT])[0]

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message=MESSAGE,
        user_performing_action=admin_user,
    )
    assert response.error is None, "Chat response should not have an error"
    assert response.top_documents is not None
    assert len(response.top_documents) == 1
    assert response.top_documents[0].document_id == short_doc.id

    # make sure this doc is really long so that it will be split into multiple chunks
    long_doc = document_builder([LONG_DOC_CONTENT])[0]

    # new chat session for simplicity
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message=MESSAGE,
        user_performing_action=admin_user,
    )
    assert response.error is None, "Chat response should not have an error"
    assert response.top_documents is not None
    assert len(response.top_documents) == 2
    # short doc should be more relevant and thus first
    assert response.top_documents[0].document_id == short_doc.id
    assert response.top_documents[1].document_id == long_doc.id


def test_send_message_disconnect_and_cleanup(
    reset: None, admin_user: DATestUser
) -> None:
    """
    Test that when a client disconnects mid-stream:
    1. Client sends a message and disconnects after receiving just 1 packet
    2. Client checks to see that their message ends up completed

    Note: There is an interim period (between disconnect and checkup) where we expect
    to see some sort of 'loading' message.
    """
    LLMProviderManager.create(user_performing_action=admin_user)

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    # Send a message and disconnect after receiving just 1 packet
    ChatSessionManager.send_message_with_disconnect(
        chat_session_id=test_chat_session.id,
        message="What are some important events that happened today?",
        user_performing_action=admin_user,
        disconnect_after_packets=1,
    )

    # Every 5 seconds, check if we have the latest state of the chat session up to a minute
    increment_seconds = 1
    max_seconds = 60
    msg = TERMINATED_RESPONSE_MESSAGE

    for _ in range(max_seconds // increment_seconds):
        time.sleep(increment_seconds)

        # Get the chat history
        chat_history = ChatSessionManager.get_chat_history(
            chat_session=test_chat_session,
            user_performing_action=admin_user,
        )

        # Find the assistant message
        assistant_message = None
        for chat_obj in chat_history:
            if chat_obj.message_type == MessageType.ASSISTANT:
                assistant_message = chat_obj
                break

        assert assistant_message is not None, "Assistant message should exist"
        msg = assistant_message.message

        if msg != TERMINATED_RESPONSE_MESSAGE:
            break

    assert msg != TERMINATED_RESPONSE_MESSAGE, (
        f"Assistant message should no longer be the terminated response message after cleanup, "
        f"got: {msg}"
    )
