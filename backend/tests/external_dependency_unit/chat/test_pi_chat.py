"""Exercise stateless host callbacks, tool effects, citations and usage projection."""

import json
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple, ExtractedContextFiles
from onyx.chat.pi.chat import ChatHost
from onyx.chat.pi.host_state import ChatHostSnapshot
from onyx.chat.pi.models import PiTextContent, PiToolCall, PiToolResult
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
    Usage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse


def test_host_search_citations_and_usage_across_callbacks() -> None:
    queue: Queue[tuple[int, Packet | Exception | object]] = Queue()
    emitter = Emitter(queue)
    state = ChatStateContainer()
    tool = MagicMock(spec=Tool)
    tool.name = "internal_search"
    tool.id = 101
    tool.description = "Search internal documents"
    tool.emitter = emitter
    tool.tool_definition.return_value = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "required": ["queries"],
            },
        },
    }
    doc = SearchDoc(
        document_id="doc",
        chunk_ind=0,
        semantic_identifier="Evidence",
        link="https://example.com/evidence",
        blurb="The answer",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    tool.run.side_effect = lambda **_: ToolResponse(
        llm_facing_response="Evidence [1]: the answer",
        rich_response=SearchDocsResponse(
            search_docs=[doc], citation_mapping={1: "doc"}
        ),
    )
    llm = LitellmLLM(
        api_key="test-tenant-key",
        model_provider="openai_compatible",
        model_name="test-model",
        api_base="https://provider.invalid",
        max_input_tokens=32000,
    )
    with (
        patch("onyx.chat.pi.chat.get_session_with_current_tenant"),
        patch(
            "onyx.chat.pi.chat.get_default_base_system_prompt",
            return_value="Answer the user.",
        ),
        patch.object(
            llm, "stream", side_effect=AssertionError("Core chat must not use LiteLLM")
        ),
        patch.object(llm, "record_usage") as usage,
    ):
        host = ChatHost(
            emitter=emitter,
            state_container=state,
            simple_chat_history=[
                ChatMessageSimple(
                    message="Search alpha and beta",
                    token_count=5,
                    message_type=MessageType.USER,
                )
            ],
            tools=[tool],
            custom_agent_prompt=None,
            persona=None,
            user_memory_context=None,
            llm=llm,
            token_counter=lambda text: len(text) // 4,
            context_files=ExtractedContextFiles(
                file_texts=[],
                image_files=[],
                use_as_search_filter=False,
                total_token_count=0,
                file_metadata=[],
                uncapped_token_count=0,
            ),
            forced_tool_id=101,
        )
        prepared = host.prepare_step(0)
        assert prepared["toolChoice"] == "required"
        calls = [
            PiToolCall(
                id=f"call_{index}",
                name="internal_search",
                arguments={"queries": [query], "limit": 2},
            )
            for index, query in enumerate(["alpha", "beta"])
        ]
        host.feed_step(
            [
                ModelResponseStream(
                    id="first",
                    created="0",
                    choice=StreamingChoice(
                        finish_reason="tool_calls",
                        delta=Delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    id=call.id,
                                    index=index,
                                    function=FunctionCall(
                                        name=call.name,
                                        arguments=json.dumps(
                                            {**call.arguments, "limit": "2"}
                                        ),
                                    ),
                                )
                                for index, call in enumerate(calls)
                            ]
                        ),
                    ),
                    usage=Usage(
                        completion_tokens=10,
                        prompt_tokens=20,
                        total_tokens=30,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0,
                    ),
                )
            ],
            finish=True,
        )
        saved = ChatHostSnapshot.model_validate_json(host.snapshot().model_dump_json())
        host.state_container = ChatStateContainer()
        host.restore(saved)
        results = host.execute_tools(calls)
        host.record_turn(
            [
                PiToolResult(
                    toolCallId=call.id,
                    toolName=call.name,
                    content=[PiTextContent(type="text", text=results[call.id])],
                    isError=False,
                )
                for call in calls
            ]
        )
        assert "Evidence [1]: the answer" in json.dumps(host.prepare_step(1))
        host.feed_step(
            [
                ModelResponseStream(
                    id="second",
                    created="0",
                    choice=StreamingChoice(
                        delta=Delta(reasoning_content="Read the evidence.")
                    ),
                )
            ]
        )
        host.feed_step(
            [
                ModelResponseStream(
                    id="second",
                    created="0",
                    choice=StreamingChoice(delta=Delta(content="The answer [1].")),
                    usage=Usage(
                        completion_tokens=10,
                        prompt_tokens=20,
                        total_tokens=30,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0,
                    ),
                )
            ],
            finish=True,
        )
        host.validate_final_response()
        state = host.state_container
    assert tool.run.call_count == 2
    assert [call.tool_call_id for call in state.tool_calls] == ["call_0", "call_1"]
    assert state.answer_tokens == "The answer [[1]](https://example.com/evidence)."
    assert state.reasoning_tokens == "Read the evidence."
    assert usage.call_count == 2
    packets = [queue.get_nowait()[1] for _ in range(queue.qsize())]
    assert any(
        isinstance(packet, Packet) and packet.obj.type == "message_delta"
        for packet in packets
    )


@pytest.mark.parametrize("mutation", ["name", "unknown", "duplicate", "unavailable"])
def test_tool_callbacks_cannot_change_recorded_tool_calls(mutation: str) -> None:
    from onyx.server.query_and_chat.placement import Placement
    from onyx.tools.models import ToolCallKickoff

    host = MagicMock(spec=ChatHost)
    tool = MagicMock(spec=Tool)
    tool.name = "internal_search"
    host.final_tools = [] if mutation == "unavailable" else [tool]
    host.state_container = ChatStateContainer()
    host.citation_processor = MagicMock()
    host.llm_step_result = MagicMock()
    host.llm_step_result.tool_calls = [
        ToolCallKickoff(
            tool_call_id="call-1",
            tool_name="internal_search",
            tool_args={"queries": ["original query"]},
            placement=Placement(turn_index=0),
        )
    ]
    call = PiToolCall(
        id="call-1", name="internal_search", arguments={"queries": ["original query"]}
    )
    if mutation == "name":
        call.name = "different_tool"
    elif mutation == "unknown":
        call.id = "unknown"
    calls = [call, call] if mutation == "duplicate" else [call]
    with patch("onyx.chat.pi.chat.run_tool_calls") as execute:
        with pytest.raises(ValueError, match="Pi requested"):
            ChatHost.execute_tools(host, calls)
        execute.assert_not_called()
