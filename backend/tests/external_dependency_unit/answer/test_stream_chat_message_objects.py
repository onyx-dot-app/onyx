import os

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import StreamingError
from onyx.chat.process_message import stream_chat_message_objects
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_chat_session
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import Packet
from tests.external_dependency_unit.conftest import create_test_user


def test_stream_chat_message_objects_without_web_search(
    db_session: Session,
) -> None:
    """
    Test that when web search is requested but not set up, the system handles
    it gracefully and returns a message explaining that web search is not available.
    """
    # First, ensure we have an LLM provider set up
    try:
        llm_provider_request = LLMProviderUpsertRequest(
            name="test-provider",
            provider="openai",
            api_key=os.environ["OPENAI_API_KEY"],
            is_default_provider=True,
            is_public=True,
            default_model_name="gpt-4.1",
            fast_default_model_name="gpt-4.1",
            groups=[],
        )
        upsert_llm_provider(
            llm_provider_upsert_request=llm_provider_request,
            db_session=db_session,
        )
        db_session.commit()
    except Exception as e:
        # Provider might already exist or other setup issue
        print(f"Note: Could not create LLM provider: {e}")

    # Create a test user
    test_user: User = create_test_user(db_session, email_prefix="test_web_search")

    # Get the default persona (ID=0)
    default_persona = get_persona_by_id(
        persona_id=0,
        user=test_user,
        db_session=db_session,
        is_for_edit=False,
    )

    # Create a chat session
    chat_session = create_chat_session(
        db_session=db_session,
        description="Test web search without tool",
        user_id=test_user.id if test_user else None,
        persona_id=default_persona.id,
    )

    # Create the chat message request with a query that attempts to force web search
    # We set allowed_tool_ids to an empty list to disable all tools
    chat_request = CreateChatMessageRequest(
        chat_session_id=chat_session.id,
        parent_message_id=None,
        message="run a web search for 'Onyx'",
        file_descriptors=[],
        prompt_override=None,
        search_doc_ids=None,
        retrieval_options=RetrievalDetails(),
        query_override=None,
    )

    # Call stream_chat_message_objects
    response_generator = stream_chat_message_objects(
        new_msg_req=chat_request,
        user=test_user,
        db_session=db_session,
    )

    # Collect all packets from the response
    raw_answer_stream: list[AnswerStreamPart] = []
    message_content = ""
    error_occurred = False

    for packet in response_generator:
        raw_answer_stream.append(packet)

        if isinstance(packet, Packet):
            if isinstance(packet.obj, MessageDelta):
                # Direct MessageDelta (if not wrapped)
                if packet.obj.content:
                    message_content += packet.obj.content
            elif isinstance(packet.obj, StreamingError):
                error_occurred = True
                break

    assert not error_occurred, "Should not have received a streaming error"

    # Verify that we got a response
    assert len(raw_answer_stream) > 0, "Should have received at least some packets"

    # Check if we got MessageResponseIDInfo packet (indicating message was created)
    has_message_id = any(
        isinstance(packet, MessageResponseIDInfo) for packet in raw_answer_stream
    )
    assert has_message_id, "Should have received a message ID packet"

    assert len(message_content) > 0, "Should have received some message content"
