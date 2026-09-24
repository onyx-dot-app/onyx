from typing import Any
from uuid import uuid4

from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.llm.mock_llm_script import MockLLMStep, MockToolCall
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser

_DUMMY_OPENAI_API_KEY = "sk-mock-llm-workflow-tests"
_BRANCHING = StreamingType.TOP_LEVEL_BRANCHING.value


def _setup(admin_user: DATestUser) -> None:
    assert app_configs.INTEGRATION_TESTS_MODE is True, (
        "Integration tests require INTEGRATION_TESTS_MODE=true."
    )
    # SearchTool is only exposed when at least one non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )


def _packet_indices(packets: list[dict[str, Any]], packet_type: str) -> list[int]:
    return [
        i for i, packet in enumerate(packets) if packet["obj"]["type"] == packet_type
    ]


def test_merged_searches_and_unknown_tool_do_not_branch(
    admin_user: DATestUser,
) -> None:
    _setup(admin_user)
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="what is the answer?",
        user_performing_action=admin_user,
        mock_llm_script=[
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_search_alpha",
                        name="internal_search",
                        arguments={"queries": ["alpha"]},
                    ),
                    MockToolCall(
                        id="call_search_beta",
                        name="internal_search",
                        arguments={"queries": ["beta"]},
                    ),
                    MockToolCall(
                        id="call_unknown",
                        name="tool_that_does_not_exist",
                        arguments={},
                    ),
                ],
            ),
            MockLLMStep(
                text="Merged answer.",
                match_prompt_contains="call_search_alpha",
            ),
        ],
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [entry.tool_call_id for entry in response.tool_call_debug] == [
        "call_search_alpha",
        "call_search_beta",
        "call_unknown",
    ]

    packets = response.packets
    assert _packet_indices(packets, _BRANCHING) == []

    search_starts = _packet_indices(packets, StreamingType.SEARCH_TOOL_START.value)
    assert len(search_starts) == 1
    queries = [
        query
        for i in _packet_indices(packets, StreamingType.SEARCH_TOOL_QUERIES_DELTA.value)
        for query in packets[i]["obj"]["queries"]
    ]
    assert "alpha" in queries
    assert "beta" in queries

    assert response.full_message == "Merged answer."


def test_distinct_executed_tools_branch_before_tool_starts(
    admin_user: DATestUser,
) -> None:
    _setup(admin_user)

    custom_tool_name = f"branching_ping_{uuid4().hex[:8]}"
    # Points at the API server itself so the call needs no external service.
    custom_tool_id = ToolManager.create_custom(
        name=custom_tool_name,
        definition={
            "openapi": "3.0.0",
            "info": {
                "title": "Branching ping",
                "description": "Health check",
                "version": "1.0.0",
            },
            "servers": [{"url": "http://localhost:8080"}],
            "paths": {
                "/health": {
                    "get": {
                        "summary": "Check API server health",
                        "operationId": custom_tool_name,
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        },
        user_performing_action=admin_user,
    )
    search_tool = ToolManager.get_by_in_code_id(
        SEARCH_TOOL_ID, user_performing_action=admin_user
    )
    assert search_tool is not None, "SearchTool must exist for this test"
    persona = PersonaManager.create(
        tool_ids=[search_tool.id, custom_tool_id],
        user_performing_action=admin_user,
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="search and ping",
        user_performing_action=admin_user,
        mock_llm_script=[
            MockLLMStep(
                tool_calls=[
                    MockToolCall(
                        id="call_search_alpha",
                        name="internal_search",
                        arguments={"queries": ["alpha"]},
                    ),
                    MockToolCall(
                        id="call_search_beta",
                        name="internal_search",
                        arguments={"queries": ["beta"]},
                    ),
                    MockToolCall(id="call_ping", name=custom_tool_name, arguments={}),
                ],
            ),
            MockLLMStep(
                text="Both tools ran.",
                match_prompt_contains="call_ping",
            ),
        ],
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"

    packets = response.packets
    branching = _packet_indices(packets, _BRANCHING)
    assert len(branching) == 1
    branching_packet = packets[branching[0]]
    assert branching_packet["obj"]["num_parallel_branches"] == 2

    search_starts = _packet_indices(packets, StreamingType.SEARCH_TOOL_START.value)
    custom_starts = _packet_indices(packets, StreamingType.CUSTOM_TOOL_START.value)
    assert len(search_starts) == 1
    assert len(custom_starts) == 1
    for start in search_starts + custom_starts:
        assert branching[0] < start
        assert (
            packets[start]["placement"]["turn_index"]
            == branching_packet["placement"]["turn_index"]
        )

    assert response.full_message == "Both tools ran."
