from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.conftest import DocumentBuilderType


def test_deep_research_runs_tool_for_simple_prompt(
    reset: None,
    admin_user: DATestUser,
) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="Hello",
        user_performing_action=admin_user,
        use_agentic_search=True,
        chat_session=test_chat_session,
    )

    tool_used = any(result.tool_name for result in response.used_tools)

    # We would like to use this, but it's not worth adding a field to get-chat-session responses
    # just for testing
    # assert (
    #     tool_used
    #     or response.research_answer_purpose
    #     == ResearchAnswerPurpose.CLARIFICATION_REQUEST
    # )

    # TODO: the second condition is a hacky way to check whether
    # we're making a clarification request.
    assert tool_used or response.full_message.startswith("1. ")


def test_send_message_simple_with_history(reset: None, admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)

    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="this is a test message",
        user_performing_action=admin_user,
    )

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
    assert response.top_documents is not None
    assert len(response.top_documents) == 2
    # short doc should be more relevant and thus first
    assert response.top_documents[0].document_id == short_doc.id
    assert response.top_documents[1].document_id == long_doc.id
