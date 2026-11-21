"""End-to-end tests for the postgres_query built-in tool.

Verifies the full activation path: a persona with internal search gets the
tool and a persona without it does not, a chat turn can run it, and results
are scoped per user (another user's chat history is invisible — empty result,
not an error or a leak). The mock LLM scripts the tool calls, so the assertions check the
tool output the model received. With code mode on, the call runs inside an
`execute_code` program and its text comes back in the program's output, so the
assertions look for the text rather than compare the whole result.
"""

from uuid import uuid4

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
    requires_code_mode,
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
_SCOPED_CALL_ID = "call_pg_scoped_count"
_PAGING_PROGRAM_ID = "call_pg_paging_program"


def _search_tool_id(admin_user: DATestUser) -> int:
    """postgres_query comes with internal search, which is offered only when a
    non-default connector exists. Call it after the test creates its own."""
    tool = ToolManager.get_by_in_code_id(
        "SearchTool", user_performing_action=admin_user
    )
    assert tool is not None and tool.id is not None
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

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    search_tool_id = _search_tool_id(admin_user)
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
        user_performing_action=admin_user, tool_ids=[search_tool_id]
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="How many test documents are there?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert "2 matching documents." in _tool_result(mock_llm, "count", _COUNT_CALL_ID)


def test_postgres_tool_chat_history_is_user_scoped(
    admin_user: DATestUser, basic_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API, user_performing_action=admin_user
    )
    search_tool_id = _search_tool_id(admin_user)
    secret = f"zanzibar-{uuid4().hex[:8]}"
    codeword_message = f"Note this codeword for later: {secret}"
    history_query: dict[str, str | bool] = {
        "table": "chat_message",
        "content_contains": secret,
    }
    ask = "Search my past chat messages for the codeword."

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
        # The tool is offered on every turn, so keep the codeword turn out.
        conditions=RequestConditions(prompt_contains=[ask]),
    )
    persona = PersonaManager.create(
        user_performing_action=admin_user, tool_ids=[search_tool_id], is_public=True
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

    for user in (admin_user, basic_user):
        session = ChatSessionManager.create(
            persona_id=persona.id, user_performing_action=user
        )
        response = ChatSessionManager.send_message(
            chat_session_id=session.id,
            message=ask,
            user_performing_action=user,
        )
        assert response.error is None, f"Unexpected stream error: {response.error}"

    # The owner finds their own past message.
    assert codeword_message in _tool_result(mock_llm, "history", _ADMIN_CALL_ID)
    # Another user gets a scoped (empty) result — no error, no leaked content.
    basic_result = _tool_result(mock_llm, "history", _BASIC_CALL_ID)
    assert "0 matching chat messages." in basic_result
    assert secret not in basic_result


def test_postgres_tool_respects_agent_document_sets(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """An agent limited to a document set counts only the documents in it."""
    tag = uuid4().hex[:8]

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pairs = [
        CCPairManager.create_from_scratch(
            source=DocumentSource.INGESTION_API,
            user_performing_action=admin_user,
        )
        for _ in range(2)
    ]
    search_tool_id = _search_tool_id(admin_user)
    for i, cc_pair in enumerate(cc_pairs):
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair,
            content=f"Scoped postgres tool test document {i}",
            api_key=api_key,
            document_id=f"pgscope-{tag}-{i}",
        )
    document_set = DocumentSetManager.create(
        user_performing_action=admin_user, cc_pair_ids=[cc_pairs[0].id]
    )

    mock_llm.conversation(
        "scoped",
        _tool_call(
            _SCOPED_CALL_ID,
            {"table": "document", "count": True, "title_contains": f"pgscope-{tag}"},
        ),
        _answer_after(_SCOPED_CALL_ID),
    )
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        tool_ids=[search_tool_id],
        document_set_ids=[document_set.id],
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="How many scoped test documents are there?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    result = _tool_result(mock_llm, "scoped", _SCOPED_CALL_ID)
    assert "limited to this agent's knowledge" in result
    assert "1 matching documents." in result


# Follows next_cursor until the last page, one document per page.
_PAGING_PROGRAM = """
cursor: str | None = None
pages = 0
titles = []
while True:
    text = await tools.postgres_query(
        table="document", title_contains="{title}", limit=1, cursor=cursor
    )
    pages += 1
    titles += [line for line in text.splitlines() if line.startswith("- [")]
    last_line = text.splitlines()[-1]
    if not last_line.startswith("next_cursor: "):
        break
    cursor = last_line[len("next_cursor: "):]
f"pages={{pages}} documents={{len(titles)}}"
"""


@requires_code_mode(True)
def test_postgres_tool_pages_through_every_document_in_a_program(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    tag = uuid4().hex[:8]

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    search_tool_id = _search_tool_id(admin_user)
    for i in range(3):
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair,
            content=f"Paged postgres tool test document {i}",
            api_key=api_key,
            document_id=f"pgpage-{tag}-{i}",
        )

    mock_llm.conversation(
        "paging",
        Reply(
            tool_calls=[
                ToolCall(
                    id=_PAGING_PROGRAM_ID,
                    name="execute_code",
                    arguments={
                        "code": _PAGING_PROGRAM.format(title=f"pgpage-{tag}"),
                        "yield_time_ms": 120_000,
                    },
                )
            ],
            conditions=RequestConditions(offers=["execute_code"]),
        ),
        _answer_after(_PAGING_PROGRAM_ID),
    )
    persona = PersonaManager.create(
        user_performing_action=admin_user, tool_ids=[search_tool_id]
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Go through every paged test document.",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert "pages=3 documents=3" in _tool_result(mock_llm, "paging", _PAGING_PROGRAM_ID)


def test_postgres_tool_comes_only_with_internal_search(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API, user_performing_action=admin_user
    )
    ask = f"Say hello. {uuid4().hex[:8]}"
    mock_llm.conversation(
        "no_search",
        Reply(text="Hello.", conditions=RequestConditions(prompt_contains=[ask])),
    )
    persona = PersonaManager.create(user_performing_action=admin_user, tool_ids=[])
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=ask,
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    [request] = mock_llm.requests_in("no_search")
    # Neither offered as a tool nor named in a code mode program's functions.
    assert _TOOL_NAME not in str(request.body)
