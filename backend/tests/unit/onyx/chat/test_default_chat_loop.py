"""End-to-end cases for the default Chat agent loop.

Each case drives the default Chat loop with a scripted provider and fake tools,
then checks the executed tools and the emitted packets.
"""

import json
import queue
from collections.abc import Iterator
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import run_llm_loop
from onyx.chat.models import ChatMessageSimple, ExtractedContextFiles
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.interfaces import LLMConfig, LLMUserIdentity
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import ReasoningEffort
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CustomToolStart,
    Packet,
    TopLevelBranching,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool

BASE_SYSTEM_PROMPT = "You are the test assistant."
USER_QUESTION = "What is Onyx?"
BUDGET_INPUT_TOKENS = 100_000
BUDGET_OUTPUT_TOKENS = 4_321


def _chunk(delta: Delta, finish_reason: str | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        id="chunk",
        created="0",
        choice=StreamingChoice(finish_reason=finish_reason, delta=delta),
    )


def answer_step(*parts: str) -> list[ModelResponseStream]:
    chunks = [_chunk(Delta(content=part)) for part in parts]
    chunks.append(_chunk(Delta(), finish_reason="stop"))
    return chunks


def tool_step(*calls: tuple[str, str, dict[str, Any]]) -> list[ModelResponseStream]:
    chunks: list[ModelResponseStream] = []
    for index, (call_id, name, args) in enumerate(calls):
        chunks.append(
            _chunk(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=call_id,
                            index=index,
                            function=FunctionCall(name=name, arguments=""),
                        )
                    ]
                )
            )
        )
        chunks.append(
            _chunk(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=None,
                            index=index,
                            function=FunctionCall(
                                name=None, arguments=json.dumps(args)
                            ),
                        )
                    ]
                )
            )
        )
    chunks.append(_chunk(Delta(), finish_reason="tool_calls"))
    return chunks


class ScriptedChatLLM:
    """Replays one scripted stream per model call and records each request."""

    def __init__(self, *steps: list[ModelResponseStream]) -> None:
        self.config = LLMConfig(
            model_provider="openai",
            model_name="gpt-test",
            temperature=0.0,
            max_input_tokens=200_000,
        )
        self._steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> Iterator[ModelResponseStream]:
        self.requests.append(kwargs)
        if not self._steps:
            raise AssertionError("the loop requested more model calls than scripted")
        yield from self._steps.pop(0)


def _token_counter(text: str) -> int:
    return len(text) // 4 + 1


def _search_response(*document_ids: str) -> ToolResponse:
    docs = [
        SearchDoc(
            document_id=doc_id,
            chunk_ind=0,
            semantic_identifier=f"Title {doc_id}",
            link=f"https://example.com/{doc_id}",
            blurb=f"blurb {doc_id}",
            source_type=DocumentSource.WEB,
            boost=1,
            hidden=False,
            metadata={},
            score=0.0,
            match_highlights=[],
        )
        for doc_id in document_ids
    ]
    mapping = {1 + i: doc_id for i, doc_id in enumerate(document_ids)}
    return ToolResponse(
        rich_response=SearchDocsResponse(search_docs=docs, citation_mapping=mapping),
        llm_facing_response=json.dumps({"results": list(document_ids)}),
    )


class _FakeBudget:
    input_tokens = BUDGET_INPUT_TOKENS

    def output_allowance(self, estimated_input_tokens: int) -> int:  # noqa: ARG002
        return BUDGET_OUTPUT_TOKENS


@dataclass
class ChatRunResult:
    packets: list[Packet]

    def packets_of(self, packet_type: type) -> list[Packet]:
        return [p for p in self.packets if isinstance(p.obj, packet_type)]


@dataclass
class ChatHarness:
    merged_queue: queue.Queue[tuple[int, Packet | Exception | object]] = field(
        default_factory=queue.Queue
    )
    emitter: Emitter = field(init=False)

    def __post_init__(self) -> None:
        self.emitter = Emitter(merged_queue=self.merged_queue)

    def tool(
        self,
        spec: type[Tool],
        name: str,
        tool_id: int,
        responses: list[ToolResponse] | None = None,
    ) -> MagicMock:
        tool = MagicMock(spec=spec)
        tool.id = tool_id
        tool.name = name
        tool.display_name = name
        tool.description = f"{name} description"
        tool.emitter = self.emitter
        tool.supports_site_filter = True
        tool.tool_definition.return_value = {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} description",
                "parameters": {
                    "type": "object",
                    "properties": {"queries": {"type": "array"}},
                },
            },
        }
        tool.emit_start.side_effect = lambda placement: self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=name, tool_id=tool_id),
            )
        )
        if responses is not None:
            tool.run.side_effect = list(responses)
        else:
            tool.run.return_value = ToolResponse(
                rich_response=None, llm_facing_response=f"{name} ok"
            )
        return tool

    def drain(self) -> list[Packet]:
        packets: list[Packet] = []
        while not self.merged_queue.empty():
            _, item = self.merged_queue.get_nowait()
            assert isinstance(item, Packet)
            packets.append(item)
        return packets


def _no_context_files() -> ExtractedContextFiles:
    return ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=None,
    )


def _run_default_chat(
    harness: ChatHarness, llm: ScriptedChatLLM, tools: list[Any]
) -> ChatRunResult:
    history = [
        ChatMessageSimple(
            message=USER_QUESTION,
            token_count=_token_counter(USER_QUESTION),
            message_type=MessageType.USER,
        )
    ]
    run_llm_loop(
        emitter=harness.emitter,
        state_container=ChatStateContainer(),
        simple_chat_history=history,
        tools=tools,
        custom_agent_prompt=None,
        context_files=_no_context_files(),
        persona=None,
        user_memory_context=None,
        llm=llm,  # ty: ignore[invalid-argument-type]
        token_counter=_token_counter,
        forced_tool_id=None,
        user_identity=LLMUserIdentity(user_id="user-1", session_id="session-1"),
        chat_session_id="session-1",
        chat_files=None,
        reasoning_effort=ReasoningEffort.LOW,
        include_citations=True,
        inject_memories_in_prompt=True,
    )
    return ChatRunResult(packets=harness.drain())


@pytest.fixture
def chat_env() -> Iterator[None]:
    with ExitStack() as stack:
        stack.enter_context(
            patch("onyx.chat.llm_loop.trace", return_value=nullcontext())
        )
        stack.enter_context(
            patch("onyx.llm.litellm_singleton.config.initialize_litellm")
        )
        stack.enter_context(
            patch(
                "onyx.chat.llm_loop.get_session_with_current_tenant",
                return_value=nullcontext(),
            )
        )
        stack.enter_context(
            patch(
                "onyx.chat.llm_loop.get_default_base_system_prompt",
                return_value=BASE_SYSTEM_PROMPT,
            )
        )
        stack.enter_context(
            patch(
                "onyx.chat.llm_loop.resolve_chat_token_budget",
                return_value=_FakeBudget(),
            )
        )
        stack.enter_context(
            patch("onyx.chat.prompt_utils.get_company_context", return_value=None)
        )
        stack.enter_context(
            patch(
                "onyx.chat.llm_loop.get_current_incognito_record_mode",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "onyx.chat.llm_loop.build_python_chat_files_from_search_docs",
                return_value=[],
            )
        )
        yield


@pytest.mark.usefixtures("chat_env")
class TestTopLevelBranching:
    def test_merged_search_calls_and_unknown_tool_do_not_branch(self) -> None:
        harness = ChatHarness()
        search = harness.tool(
            SearchTool,
            SearchTool.NAME,
            11,
            responses=[_search_response("docA")],
        )
        llm = ScriptedChatLLM(
            tool_step(
                ("c1", SearchTool.NAME, {"queries": ["alpha"]}),
                ("c2", SearchTool.NAME, {"queries": ["beta"]}),
                ("c3", "unknown_tool", {}),
            ),
            answer_step("Onyx is great [1]."),
        )

        result = _run_default_chat(harness, llm, [search])

        assert search.run.call_count == 1
        run_kwargs = search.run.call_args.kwargs
        assert run_kwargs["queries"] == ["alpha", "beta"]
        assert run_kwargs["placement"] == Placement(turn_index=0, tab_index=0)
        assert result.packets_of(TopLevelBranching) == []

    def test_distinct_executed_tools_branch_before_tool_starts(self) -> None:
        harness = ChatHarness()
        search = harness.tool(
            SearchTool,
            SearchTool.NAME,
            11,
            responses=[_search_response("docA")],
        )
        other = harness.tool(Tool, "other_tool", 12)
        llm = ScriptedChatLLM(
            tool_step(
                ("c1", SearchTool.NAME, {"queries": ["alpha"]}),
                ("c2", SearchTool.NAME, {"queries": ["beta"]}),
                ("c3", "other_tool", {}),
                ("c4", "unknown_tool", {}),
            ),
            answer_step("done"),
        )

        result = _run_default_chat(harness, llm, [search, other])

        assert search.run.call_count == 1
        assert other.run.call_count == 1
        branching = result.packets_of(TopLevelBranching)
        assert len(branching) == 1
        assert branching[0].obj.num_parallel_branches == 2  # ty: ignore[unresolved-attribute]
        assert branching[0].placement.turn_index == 0

        starts = result.packets_of(CustomToolStart)
        assert len(starts) == 2
        branching_index = result.packets.index(branching[0])
        assert all(result.packets.index(p) > branching_index for p in starts)
