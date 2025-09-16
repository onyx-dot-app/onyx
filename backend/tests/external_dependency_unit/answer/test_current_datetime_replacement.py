import os
from datetime import datetime

from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import StreamingError
from onyx.chat.process_message import stream_chat_message_objects
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_chat_session
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import MessageDelta
from tests.external_dependency_unit.conftest import create_test_user


def test_stream_chat_current_date_response(
    db_session, full_deployment_setup, mock_external_deps
):
    """Smoke test that asking for current date yields a streamed response.

    This exercises the full chat path using the default persona, ensuring
    the system prompt makes it to the LLM and a response is returned.
    """
    # Ensure LLM provider exists
    try:
        llm_provider_request = LLMProviderUpsertRequest(
            name="test-provider",
            provider="openai",
            api_key=os.environ.get("OPENAI_API_KEY", "test"),
            is_public=True,
            default_model_name="gpt-4.1",
            fast_default_model_name="gpt-4.1",
            groups=[],
        )
        provider = upsert_llm_provider(
            llm_provider_upsert_request=llm_provider_request, db_session=db_session
        )
        update_default_provider(provider.id, db_session)
    except Exception as e:
        print(f"Note: Could not create LLM provider: {e}")

    # Create user, persona, session
    test_user: User = create_test_user(db_session, email_prefix="test_current_date")
    default_persona = get_persona_by_id(
        persona_id=0, user=test_user, db_session=db_session, is_for_edit=False
    )
    chat_session = create_chat_session(
        db_session=db_session,
        description="Test current date question",
        user_id=test_user.id if test_user else None,
        persona_id=default_persona.id,
    )

    chat_request = CreateChatMessageRequest(
        chat_session_id=chat_session.id,
        parent_message_id=None,
        message="What is the current date?",
        file_descriptors=[],
        prompt_override=None,
        search_doc_ids=None,
        retrieval_options=RetrievalDetails(),
        query_override=None,
    )

    gen = stream_chat_message_objects(
        new_msg_req=chat_request, user=test_user, db_session=db_session
    )

    raw: list[AnswerStreamPart] = []
    content = ""
    had_error = False

    for pkt in gen:
        raw.append(pkt)
        if hasattr(pkt, "obj") and isinstance(pkt.obj, MessageDelta):
            if pkt.obj.content:
                content += pkt.obj.content
        if hasattr(pkt, "obj") and isinstance(pkt.obj, StreamingError):
            had_error = True
            break

    assert not had_error, "Should not error when answering current date"
    assert any(
        isinstance(p, MessageResponseIDInfo) for p in raw
    ), "Should yield a message ID"
    assert len(content) > 0, "Should stream some assistant content"

    # Validate answer likely contains current date information
    now = datetime.now()
    month_name = now.strftime("%B")
    year = now.strftime("%Y")

    # Require at least month name and year to appear to avoid overfitting to exact format
    assert (
        month_name in content and year in content
    ), f"Expected month '{month_name}' and year '{year}' in answer, got: {content[:200]}..."
