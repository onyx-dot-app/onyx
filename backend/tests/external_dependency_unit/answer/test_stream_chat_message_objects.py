import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.chat import create_chat_session
from onyx.db.models import User
from onyx.db.persona import upsert_persona
from onyx.llm.litellm_models import Delta
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_utils import final_answer
from tests.external_dependency_unit.conftest import create_test_user
from tests.unit.onyx.agents.fakes import ScriptedLLM


def test_stream_chat_message_objects_without_web_search(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
) -> None:
    """An assistant without web search excludes it from model requests."""
    ensure_default_llm_provider(db_session)

    test_user: User = create_test_user(db_session, email_prefix="test_web_search")

    test_persona = upsert_persona(
        user=None,  # System persona
        name=f"Test Persona {uuid.uuid4()}",
        description="Test persona with no tools for web search test",
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=True,
        db_session=db_session,
        tool_ids=[],  # Explicitly no tools
        document_set_ids=None,
        is_listed=True,
        default_model_configuration_id=None,
    )

    chat_session = create_chat_session(
        db_session=db_session,
        description="Test web search without tool",
        user_id=test_user.id,
        persona_id=test_persona.id,
    )
    chat_request = SendMessageRequest(
        message="run a web search for 'Onyx'",
        chat_session_id=chat_session.id,
    )
    response_generator = handle_stream_message_objects(
        new_msg_req=chat_request,
        user=test_user,
    )
    llm = ScriptedLLM([Delta(content="Web search is unavailable for this assistant.")])
    with patch("onyx.chat.prepare.get_llm_for_persona", return_value=llm):
        raw = list(response_generator)
    assert "web_search" not in {
        tool["function"]["name"] for tool in llm.requests[0]["tools"]
    }
    assert final_answer(raw)
    assert any(isinstance(part, MessageResponseIDInfo) for part in raw)
