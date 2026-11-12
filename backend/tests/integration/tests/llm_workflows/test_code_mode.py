"""Code mode through the real server: the model calls tools from an
`execute_code` program, which runs in the sandbox and is saved with the chat."""

from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
    requires_code_mode,
)
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser, ToolName
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

pytestmark = requires_code_mode(True)

_SEARCH_PROGRAM_ID = "call_program_search"
_LOAD_PROGRAM_ID = "call_program_load"
_ANSWER = "The program searched the documents."


def _program(call_id: str, code: str) -> Reply:
    return Reply(
        tool_calls=[
            ToolCall(
                id=call_id,
                name="execute_code",
                # Keeps a slow search inside the first observation.
                arguments={"code": code, "yield_time_ms": 120_000},
            )
        ],
        # The search is a function of programs, not a tool of its own.
        conditions=RequestConditions(
            offers=["execute_code"], does_not_offer=["internal_search"]
        ),
    )


def test_program_runs_nested_search_and_keeps_its_store_across_messages(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    # internal_search is only offered when a non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    [search_tool_id] = [
        tool.id
        for tool in ToolManager.list_tools(user_performing_action=admin_user)
        if tool.in_code_tool_id == SEARCH_TOOL_ID
    ]
    persona = PersonaManager.create(
        tool_ids=[search_tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    mock_llm.conversation(
        "chat",
        _program(
            _SEARCH_PROGRAM_ID,
            'found = await internal_search(queries=["alpha"])\n'
            'store("note", "kept")\n'
            'print("searched")',
        ),
        Reply(
            text=_ANSWER,
            conditions=RequestConditions(has_results_for=[_SEARCH_PROGRAM_ID]),
        ),
        _program(_LOAD_PROGRAM_ID, 'print("loaded", load("note"))'),
        Reply(
            text="The note was kept.",
            conditions=RequestConditions(has_results_for=[_LOAD_PROGRAM_ID]),
        ),
    )

    first = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Search for alpha.",
        user_performing_action=admin_user,
        preferred_tool_id=search_tool_id,
    )

    assert first.error is None, f"Unexpected stream error: {first.error}"
    assert first.full_message == _ANSWER
    program, search = first.tool_call_debug
    assert (program.tool_call_id, program.tool_name) == (
        _SEARCH_PROGRAM_ID,
        "execute_code",
    )
    assert search.tool_call_id.startswith(f"{_SEARCH_PROGRAM_ID}:")
    assert (search.tool_name, search.tool_args) == (
        "internal_search",
        {"queries": ["alpha"]},
    )
    # The nested search streams as a search step of its own.
    assert [tool.tool_name for tool in first.used_tools] == [ToolName.INTERNAL_SEARCH]
    program_request, answer_request = mock_llm.requests_in("chat")
    assert "internal_search (a function in `execute_code` programs)" in str(
        program_request.body["messages"]
    )
    assert "searched" in (answer_request.tool_result(_SEARCH_PROGRAM_ID) or "")

    # A reload replays the nested search from the saved program result.
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    response.raise_for_status()
    [replayed] = response.json()["packets"]
    replayed_types = [packet["obj"]["type"] for packet in replayed]
    assert replayed_types.count(StreamingType.CODE_MODE_START.value) == 1
    assert replayed_types.count(StreamingType.SEARCH_TOOL_START.value) == 1

    # A program in a later message reads the value that the first one stored.
    second = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What did the last program keep?",
        user_performing_action=admin_user,
    )

    assert second.error is None, f"Unexpected stream error: {second.error}"
    assert second.full_message == "The note was kept."
    load_answer_request = mock_llm.requests_in("chat")[-1]
    assert "loaded kept" in (load_answer_request.tool_result(_LOAD_PROGRAM_ID) or "")
