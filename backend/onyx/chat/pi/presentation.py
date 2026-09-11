"""Project streamed model output into Onyx UI packets and partial-save state."""

import json
from collections.abc import Iterable
from typing import Any

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import LlmStepResult
from onyx.chat.pi.host_state import PendingToolCall, PresentationSnapshot
from onyx.chat.tool_call_args_streaming import maybe_emit_argument_delta
from onyx.context.search.models import SearchDoc
from onyx.llm.model_response import ModelResponseStream, Usage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    Packet,
    ReasoningDelta,
    ReasoningDone,
    ReasoningStart,
)
from onyx.tools.models import ToolCallKickoff
from onyx.utils.jsonriver import Parser


class ChatPresentation:
    def __init__(
        self,
        emitter: Emitter,
        state: ChatStateContainer,
        citations: DynamicCitationProcessor,
        turn_index: int,
        documents: list[SearchDoc] | None,
        processing_seconds: float,
    ) -> None:
        self.emitter = emitter
        self.state = state
        self.citations = citations
        self.turn_index = turn_index
        self.documents = documents
        self.processing_seconds = processing_seconds
        self.reasoning = ""
        self.answer = ""
        self.raw_answer = ""
        self.reasoning_open = False
        self.answer_open = False
        self.reasoning_sections = 0
        self.calls: list[ToolCallKickoff] = []
        self.argument_parsers: dict[int, Parser] = {}
        self.pending_calls: dict[int, dict[str, Any]] = {}
        self.usage: Usage | None = None
        self.finish_reason: str | None = None

    def emit(self, packet: Packet) -> None:
        self.emitter.emit(packet)

    @property
    def placement(self) -> Placement:
        return Placement(turn_index=self.turn_index)

    def close_reasoning(self) -> None:
        if self.reasoning_open:
            self.emit(Packet(placement=self.placement, obj=ReasoningDone()))
            self.reasoning_open = False
            self.reasoning_sections += 1
            self.turn_index += 1

    def emit_citations(self, results: Iterable[str | CitationInfo]) -> None:
        for result in results:
            if isinstance(result, str):
                self.answer += result
                self.state.set_answer_tokens(self.answer)
                self.emit(
                    Packet(
                        placement=self.placement, obj=AgentResponseDelta(content=result)
                    )
                )
            else:
                self.state.add_emitted_citation(result.citation_number)
                self.emit(Packet(placement=self.placement, obj=result))

    def feed(self, chunk: ModelResponseStream) -> None:
        if chunk.usage:
            self.usage = chunk.usage
        if chunk.choice.finish_reason:
            self.finish_reason = chunk.choice.finish_reason
        delta = chunk.choice.delta
        if delta.reasoning_content:
            if not self.reasoning_open:
                self.emit(Packet(placement=self.placement, obj=ReasoningStart()))
                self.reasoning_open = True
            self.reasoning += delta.reasoning_content
            self.state.set_reasoning_tokens(self.reasoning)
            self.emit(
                Packet(
                    placement=self.placement,
                    obj=ReasoningDelta(reasoning=delta.reasoning_content),
                )
            )
        if delta.content:
            self.close_reasoning()
            if not self.answer_open:
                self.answer_open = True
                self.state.set_pre_answer_processing_time(self.processing_seconds)
                self.emit(
                    Packet(
                        placement=self.placement,
                        obj=AgentResponseStart(
                            final_documents=self.documents,
                            pre_answer_processing_seconds=self.processing_seconds,
                        ),
                    )
                )
            self.raw_answer += delta.content
            self.emit_citations(self.citations.process_token(delta.content))
        if delta.tool_calls:
            self.close_reasoning()
            for call in delta.tool_calls:
                pending = self.pending_calls.setdefault(
                    call.index, {"id": "", "name": "", "arguments": ""}
                )
                if call.id:
                    pending["id"] = call.id
                if call.function and call.function.name:
                    pending["name"] = call.function.name
                if not chunk.choice.finish_reason:
                    if call.function and call.function.arguments:
                        pending["arguments"] += call.function.arguments
                    for packet in maybe_emit_argument_delta(
                        self.pending_calls,
                        call,
                        self.placement,
                        self.argument_parsers,
                    ):
                        self.emit(packet)
                else:
                    if not call.id or not call.function or not call.function.name:
                        raise ValueError("Pi returned an incomplete tool call")
                    self.calls.append(
                        ToolCallKickoff(
                            tool_call_id=call.id,
                            tool_name=call.function.name,
                            tool_args=json.loads(call.function.arguments or "{}"),
                            placement=Placement(
                                turn_index=self.turn_index, tab_index=call.index
                            ),
                        )
                    )

    def finish(self) -> LlmStepResult:
        self.close_reasoning()
        self.emit_citations(self.citations.process_token(None))
        self.citations.curr_segment = ""
        self.state.set_citation_mapping(self.citations.citation_to_doc)
        return LlmStepResult(
            reasoning=self.reasoning or None,
            answer=self.answer or None,
            raw_answer=self.raw_answer or None,
            tool_calls=self.calls or None,
            finish_reason=self.finish_reason,
        )

    def snapshot(self) -> PresentationSnapshot:
        return PresentationSnapshot(
            turn_index=self.turn_index,
            documents=self.documents,
            processing_seconds=self.processing_seconds,
            reasoning=self.reasoning,
            answer=self.answer,
            raw_answer=self.raw_answer,
            reasoning_open=self.reasoning_open,
            answer_open=self.answer_open,
            reasoning_sections=self.reasoning_sections,
            calls=self.calls,
            pending_calls={
                index: PendingToolCall.model_validate(call)
                for index, call in self.pending_calls.items()
            },
            parser_indices=set(self.argument_parsers),
            usage=self.usage,
            finish_reason=self.finish_reason,
        )

    @classmethod
    def restore(
        cls,
        snapshot: PresentationSnapshot,
        emitter: Emitter,
        state: ChatStateContainer,
        citations: DynamicCitationProcessor,
    ) -> "ChatPresentation":
        presenter = cls(
            emitter,
            state,
            citations,
            snapshot.turn_index,
            snapshot.documents,
            snapshot.processing_seconds,
        )
        presenter.reasoning = snapshot.reasoning
        presenter.answer = snapshot.answer
        presenter.raw_answer = snapshot.raw_answer
        presenter.reasoning_open = snapshot.reasoning_open
        presenter.answer_open = snapshot.answer_open
        presenter.reasoning_sections = snapshot.reasoning_sections
        presenter.calls = list(snapshot.calls)
        presenter.pending_calls = {
            index: call.model_dump() for index, call in snapshot.pending_calls.items()
        }
        presenter.usage = snapshot.usage
        presenter.finish_reason = snapshot.finish_reason
        for index in snapshot.parser_indices:
            parser = Parser()
            parser.feed(snapshot.pending_calls[index].arguments)
            presenter.argument_parsers[index] = parser
        return presenter
