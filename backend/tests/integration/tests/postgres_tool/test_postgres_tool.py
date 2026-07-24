"""End-to-end tests for the postgres_query built-in tool.

Verifies the full activation path: the seed migration created the tool row,
a persona can attach it, a chat turn can run it, and results are scoped per
user (another user's chat history is invisible — empty result, not an error
or a leak). The mock LLM scripts the tool calls, so the assertions check the
exact tool output the model received.
"""

from uuid import uuid4

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
    tool_call_reply,
)
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

_TOOL_NAME = "postgres_query"
_COUNT_CALL_ID = "call_pg_count"
_ADMIN_CALL_ID = "call_pg_history_admin"
_BASIC_CALL_ID = "call_pg_history_basic"


def _get_postgres_tool_id(admin_user: DATestUser) -> int:
    tool = ToolManager.get_by_in_code_id(
        "PostgresTool", user_performing_action=admin_user
    )
    assert tool is not None, "PostgresTool should be seeded by the alembic migration"
    assert tool.id is not None
    return tool.id


def _tool_call(call_id: str, arguments: dict[str, str | bool]) -> Reply:
    return tool_call_reply(
        ToolCall(id=call_id, name=_TOOL_NAME, arguments=arguments),
        tool_choice="auto",
    )


def _answer_after(call_id: str) -> Reply:
    return Reply(text="Done.", conditions=RequestConditions(has_results_for=[call_id]))


def _tool_result(mock_llm: MockLLMScript, conversation: str, call_id: str) -> str:
    for request in mock_llm.requests_in(conversation):
        if (result := request.tool_result(call_id)) is not None:
            return result
    raise AssertionError(f"No tool result recorded for {call_id}")


def test_postgres_tool_counts_documents(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    tag = uuid4().hex[:8]
    tool_id = _get_postgres_tool_id(admin_user)

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    for i in range(2):
        # Doc ids surface in the title: "Test Document pgtool-<tag>-<i>"
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair,
            content=f"Postgres tool test document number {i}",
            api_key=api_key,
            document_id=f"pgtool-{tag}-{i}",
        )

    mock_llm.conversation(
        "count",
        _tool_call(
            _COUNT_CALL_ID,
            {"table": "document", "count": True, "title_contains": f"pgtool-{tag}"},
        ),
        _answer_after(_COUNT_CALL_ID),
    )
    persona = PersonaManager.create(
        user_performing_action=admin_user, tool_ids=[tool_id]
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="How many test documents are there?",
        user_performing_action=admin_user,
        preferred_tool_id=tool_id,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert _tool_result(mock_llm, "count", _COUNT_CALL_ID) == "2 matching documents."


def test_postgres_tool_chat_history_is_user_scoped(
    admin_user: DATestUser, basic_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    tool_id = _get_postgres_tool_id(admin_user)
    secret = f"zanzibar-{uuid4().hex[:8]}"
    codeword_message = f"Note this codeword for later: {secret}"
    history_query: dict[str, str | bool] = {
        "table": "chat_message",
        "content_contains": secret,
    }

    mock_llm.conversation(
        "past",
        Reply(
            text="Noted.",
            conditions=RequestConditions(prompt_contains=[codeword_message]),
        ),
    )
    mock_llm.conversation(
        "history",
        _tool_call(_ADMIN_CALL_ID, history_query),
        _answer_after(_ADMIN_CALL_ID),
        _tool_call(_BASIC_CALL_ID, history_query),
        _answer_after(_BASIC_CALL_ID),
    )
    persona = PersonaManager.create(
        user_performing_action=admin_user, tool_ids=[tool_id], is_public=True
    )

    # The admin has a past conversation containing the secret.
    past_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    ChatSessionManager.send_message(
        chat_session_id=past_session.id,
        message=codeword_message,
        user_performing_action=admin_user,
    )

    ask = "Search my past chat messages for the codeword."
    for user in (admin_user, basic_user):
        session = ChatSessionManager.create(
            persona_id=persona.id, user_performing_action=user
        )
        response = ChatSessionManager.send_message(
            chat_session_id=session.id,
            message=ask,
            user_performing_action=user,
            preferred_tool_id=tool_id,
        )
        assert response.error is None, f"Unexpected stream error: {response.error}"

    # The owner finds their own past message.
    assert codeword_message in _tool_result(mock_llm, "history", _ADMIN_CALL_ID)
    # Another user gets a scoped (empty) result — no error, no leaked content.
    basic_result = _tool_result(mock_llm, "history", _BASIC_CALL_ID)
    assert basic_result.startswith("0 matching chat messages.")
    assert secret not in basic_result
