from datetime import datetime

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import StreamingError
from onyx.chat.process_message import stream_chat_message_objects
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_chat_session
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import MessageDelta
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user


def test_stream_chat_current_date_response(
    db_session: Session, full_deployment_setup: None, mock_external_deps: None
) -> None:
    """Smoke test that asking for current date yields a streamed response.

    This exercises the full chat path using the default persona, ensuring
    the system prompt makes it to the LLM and a response is returned.
    """
    # Ensure LLM provider exists
    ensure_default_llm_provider(db_session)

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
