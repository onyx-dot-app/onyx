"""Scripted provider, fake tools, and packet helpers for Deep Research tests."""

import json
import queue
import threading
from collections.abc import Iterator, Sequence
from typing import Any

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import LLM_INVOKE_TIMEOUT_S, LLM_SOCKET_READ_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ReasoningEffort,
    ToolChoice,
)
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import ChatCompletionMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse

Chunks = list[ModelResponseStream]


def _chunk(delta: Delta, finish_reason: str | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        id="chunk",
        created="0",
        choice=StreamingChoice(delta=delta, finish_reason=finish_reason),
    )


def text(content: str) -> Chunks:
    return [_chunk(Delta(content=content))]


def tool_call_chunks(
    call_id: str, name: str, argument_chunks: list[str], index: int = 0
) -> Chunks:
    """A provider tool call: one delta with id/name, then one per argument chunk."""
    start = ChatCompletionDeltaToolCall(
        id=call_id, index=index, function=FunctionCall(name=name, arguments="")
    )
    return [_chunk(Delta(tool_calls=[start]))] + [
        _chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=None,
                        index=index,
                        function=FunctionCall(name=None, arguments=arguments),
                    )
                ]
            )
        )
        for arguments in argument_chunks
    ]


def tool_call(
    call_id: str, name: str, arguments: dict[str, Any], index: int = 0
) -> Chunks:
    return tool_call_chunks(call_id, name, [json.dumps(arguments)], index)


class ScriptedLLM(LLM):
    """Returns one scripted chunk list per stream() call and records each request."""

    def __init__(
        self,
        script: Sequence[Chunks],
    ) -> None:
        self._script = list(script)
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="scripted-model",
            temperature=0.0,
            max_input_tokens=200_000,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_s: float = LLM_INVOKE_TIMEOUT_S,
    ) -> ModelResponse:
        raise NotImplementedError

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,  # noqa: ARG002
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,  # noqa: ARG002
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,  # noqa: ARG002
    ) -> Iterator[ModelResponseStream]:
        request: dict[str, Any] = {
            "prompt": prompt,
            "tool_names": [t["function"]["name"] for t in tools or []],
            "tool_choice": tool_choice,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
        }
        with self._lock:
            self.calls.append(request)
            if not self._script:
                raise AssertionError("ScriptedLLM received an unscripted call")
            chunks = self._script.pop(0)
        yield from chunks


def prompt_messages(request: dict[str, Any]) -> list[ChatCompletionMessage]:
    prompt = request["prompt"]
    assert isinstance(prompt, list)
    return prompt


def make_emitter() -> tuple[
    Emitter, "queue.Queue[tuple[int, Packet | Exception | object]]"
]:
    merged: queue.Queue[tuple[int, Packet | Exception | object]] = queue.Queue()
    return Emitter(merged_queue=merged), merged


def drain(
    merged: "queue.Queue[tuple[int, Packet | Exception | object]]",
) -> list[Packet]:
    packets: list[Packet] = []
    while not merged.empty():
        _, item = merged.get_nowait()
        assert isinstance(item, Packet)
        packets.append(item)
    return packets


def summarize(packets: list[Packet]) -> list[tuple[str, int, int, int | None]]:
    """(packet type, turn_index, tab_index, sub_turn_index) in emission order."""
    summary: list[tuple[str, int, int, int | None]] = []
    for packet in packets:
        placement = packet.placement
        assert placement is not None
        summary.append(
            (
                type(packet.obj).__name__,
                placement.turn_index,
                placement.tab_index,
                placement.sub_turn_index,
            )
        )
    return summary


def make_search_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier=f"Doc {document_id}",
        link=f"https://example.com/{document_id}",
        blurb=f"blurb for {document_id}",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        score=1.0,
        match_highlights=[],
    )


class FakeSearchTool(Tool[None]):
    """Search-shaped tool: returns one SearchDocsResponse per call."""

    def __init__(
        self,
        name: str,
        emitter: Emitter,
        tool_id: int,
        doc_ids: list[str],
    ) -> None:
        super().__init__(emitter=emitter)
        self._name = name
        self._tool_id = tool_id
        self._doc_ids = doc_ids
        self.runs: list[tuple[Placement, dict[str, Any]]] = []

    @property
    def id(self) -> int:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} description"

    @property
    def display_name(self) -> str:
        return self._name

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["queries"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:  # noqa: ARG002
        pass

    def run(
        self,
        placement: Placement,
        override_kwargs: None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        self.runs.append((placement, dict(llm_kwargs)))
        docs = [make_search_doc(doc_id) for doc_id in self._doc_ids]
        return ToolResponse(
            rich_response=SearchDocsResponse(
                search_docs=docs,
                citation_mapping=dict(enumerate(self._doc_ids, start=1)),
            ),
            llm_facing_response=f"{self._name} results for {llm_kwargs}",
        )


def token_counter(value: str) -> int:
    return len(value) // 4 + 1
