"""Code mode through the real server: the model calls tools from an
`exec` program, which runs in the sandbox and is saved with the chat."""

from collections.abc import Callable
from contextlib import ExitStack
from uuid import uuid4

from onyx.configs.constants import DocumentSource
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.models import CapabilityEntry, ToolOptions
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.integration_rows import link_persona
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.integration import IntegrationManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
    requires_code_mode,
)
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import (
    DATestLLMProvider,
    DATestUser,
    ToolName,
)
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
                name="exec",
                # Keeps a slow search inside the first observation.
                arguments={"code": code, "yield_time_ms": 120_000},
            )
        ],
        # The search is a function of programs, not a tool of its own.
        conditions=RequestConditions(
            offers=["exec"], does_not_offer=["internal_search"]
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
            'found = await tools.internal_search(queries=["alpha"])\n'
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
        tool_options=ToolOptions(preferred=CapabilityEntry(tool_id=search_tool_id)),
    )

    assert first.error is None, f"Unexpected stream error: {first.error}"
    assert first.full_message == _ANSWER
    program, search = first.tool_call_debug
    assert (program.tool_call_id, program.tool_name) == (
        _SEARCH_PROGRAM_ID,
        "exec",
    )
    assert search.tool_call_id.startswith(f"{_SEARCH_PROGRAM_ID}:")
    assert (search.tool_name, search.tool_args) == (
        "internal_search",
        {"queries": ["alpha"]},
    )
    # The nested search streams as a search step of its own.
    assert [tool.tool_name for tool in first.used_tools] == [ToolName.INTERNAL_SEARCH]
    program_request, answer_request = mock_llm.requests_in("chat")
    assert "tools.internal_search (a function in `exec` programs)" in str(
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


_PING_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Ping", "description": "Ping", "version": "1.0.0"},
    "servers": [{"url": "https://example.com"}],
    "paths": {
        "/ping": {
            "get": {
                "summary": "Ping the service",
                "operationId": "ping",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}
_CLAUDE_PROGRAM = (
    'found = await search_tools("ping", max=1)\n'
    'described = await describe_tool(found[0]["name"])\n'
    'print("found", len(found), described["stub"] == found[0]["stub"])\n'
    "try:\n"
    '    await describe_tool("no_such_function")\n'
    "except Exception as error:\n"
    '    print("unknown:", error)\n'
    "yield_control()\n"
    'print("after the yield")'
)


def _replayed_code_cells(packets: list[dict]) -> int:
    return [packet["obj"]["type"] for packet in packets].count(
        StreamingType.CODE_MODE_START.value
    )


def test_a_claude_model_runs_programs_with_repl_and_poll(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    mock_llm_of_family: Callable[[ToolFamily], DATestLLMProvider | None],
) -> None:
    """A Claude model gets the shape it is trained on: `repl` and `poll`, and
    `search_tools` and `describe_tool` in programs. A chat that switches to it
    keeps the cells and calls of the other shape."""
    nonce = uuid4().hex
    claude = mock_llm_of_family(ToolFamily.CLAUDE)
    assert claude is not None
    with ExitStack() as cleanup:
        integration_id = IntegrationManager.create(
            {
                "for_organization": True,
                "name": f"ping-{nonce}",
                "description": "Ping a service",
                "auth_mode": "none",
                "auth_method": None,
                "config": {"shape": "openapi", "openapi_spec": _PING_SPEC},
            },
            admin_user,
        ).id
        cleanup.callback(
            lambda: IntegrationManager.delete(
                integration_id, admin_user
            ).raise_for_status()
        )
        persona = PersonaManager.create(tool_ids=[], user_performing_action=admin_user)

        @cleanup.callback
        def _delete_persona() -> None:
            assert PersonaManager.delete(persona, user_performing_action=admin_user)

        link_persona(persona.id, integration_id, {})
        mock_llm.conversation(
            nonce,
            # The other shape starts cell 1 and leaves it running.
            Reply(
                tool_calls=[
                    ToolCall(
                        id="exec-program",
                        name="exec",
                        arguments={"code": "yield_control()\nawait asyncio.sleep(60)"},
                    )
                ],
                conditions=RequestConditions(
                    offers=["exec", "wait"], does_not_offer=["repl", "poll"]
                ),
            ),
            Reply(
                text="Left it running.",
                conditions=RequestConditions(has_results_for=["exec-program"]),
            ),
            Reply(
                tool_calls=[
                    ToolCall(id="poll-old", name="poll", arguments={"cell_id": 1})
                ],
                conditions=RequestConditions(
                    offers=["repl", "poll"], does_not_offer=["exec", "wait"]
                ),
            ),
            Reply(
                tool_calls=[
                    ToolCall(
                        id="repl-program",
                        name="repl",
                        arguments={"code": _CLAUDE_PROGRAM},
                    )
                ],
                conditions=RequestConditions(has_results_for=["poll-old"]),
            ),
            Reply(
                tool_calls=[
                    ToolCall(
                        id="poll-new",
                        name="poll",
                        arguments={"cell_id": 2, "timeout": 30_000},
                    )
                ],
                conditions=RequestConditions(has_results_for=["repl-program"]),
            ),
            # A program that runs past its 1-second timeout returns, and poll
            # stops it. It ends well before the 30-second default, so it still
            # runs only when the call honors the timeout.
            Reply(
                tool_calls=[
                    ToolCall(
                        id="repl-slow",
                        name="repl",
                        arguments={
                            "code": 'await asyncio.sleep(8)\nprint("late")',
                            "timeout": 1_000,
                        },
                    )
                ],
                conditions=RequestConditions(has_results_for=["poll-new"]),
            ),
            Reply(
                tool_calls=[
                    ToolCall(
                        id="poll-stop",
                        name="poll",
                        arguments={"cell_id": 3, "terminate": True},
                    )
                ],
                conditions=RequestConditions(has_results_for=["repl-slow"]),
            ),
            Reply(
                text="Done.",
                conditions=RequestConditions(has_results_for=["poll-stop"]),
            ),
            conditions=RequestConditions(prompt_contains=[nonce]),
        )
        session = ChatSessionManager.create(
            persona_id=persona.id, user_performing_action=admin_user
        )

        @cleanup.callback
        def _delete_session() -> None:
            assert ChatSessionManager.delete(session, admin_user)

        first = ChatSessionManager.send_message(
            session.id, f"Start a cell. {nonce}", admin_user
        )
        assert first.error is None, first.error
        second = ChatSessionManager.send_message(
            session.id,
            f"Use the ping tool. {nonce}",
            admin_user,
            llm_override=LLMOverride(
                model_configuration_id=claude.model_configuration_ids[0]
            ),
        )
        # The model reads the rejected poll; the stream shows it as an error.
        assert second.full_message == "Done."

        requests = mock_llm.requests_in(nonce)
        definitions = {
            tool["function"]["name"]: tool["function"]
            for tool in requests[2].body["tools"]
        }
        assert set(definitions["repl"]["parameters"]["properties"]) == {
            "code",
            "timeout",
        }
        assert set(definitions["poll"]["parameters"]["properties"]) == {
            "cell_id",
            "timeout",
            "terminate",
        }
        assert "await search_tools(query)" in definitions["repl"]["description"]
        assert "await describe_tool(name)" in definitions["repl"]["description"]
        # The question tool has the name Claude models are trained on.
        assert "ask_user_question" in definitions
        assert "request_user_input" not in definitions
        # A poll observes the cell that the other shape started.
        assert "Cell 1 stopped when the response ended. Start a new repl call." in (
            requests[3].tool_result("poll-old") or ""
        )
        started = requests[4].tool_result("repl-program") or ""
        assert "found 1 True" in started
        assert "unknown: No tool function is named 'no_such_function'" in started
        assert "Execution running in cell 2" in started
        assert "Call poll(cell_id=2)" in started
        assert "after the yield" in (requests[5].tool_result("poll-new") or "")
        assert "Execution running in cell 3" in (
            requests[6].tool_result("repl-slow") or ""
        )
        stopped = requests[7].tool_result("poll-stop") or ""
        assert "Execution terminated in cell 3" in stopped
        assert "late" not in stopped

        # A reload renders the calls of both shapes as code cells.
        response = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{session.id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        response.raise_for_status()
        first_packets, second_packets = response.json()["packets"]
        assert _replayed_code_cells(first_packets) == 1
        assert _replayed_code_cells(second_packets) == 5
