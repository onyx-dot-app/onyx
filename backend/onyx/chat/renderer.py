"""Project semantic generation events into Onyx packets without model or storage I/O."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.context.search.models import SearchDoc
from onyx.llm.models import (
    GenerationEvent,
    GenerationTextEvent,
    GenerationToolCallEvent,
    ToolCall,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CodingAgentThinkingDelta,
    DeepResearchPlanDelta,
    DeepResearchPlanStart,
    IntermediateReportCitedDocs,
    IntermediateReportDelta,
    IntermediateReportStart,
    Packet,
    ReasoningDelta,
    ReasoningDone,
    ReasoningStart,
    SectionEnd,
    ToolCallArgumentDelta,
)


class RenderConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    placement: Placement = Field(default_factory=lambda: Placement(turn_index=0))
    citations: DynamicCitationProcessor | None = None
    documents: list[SearchDoc] | None = None
    mode: Literal["answer", "plan", "report", "coding_thinking", "silent"] = "answer"
    text_as_thinking: bool = False
    think_tool: str | None = None
    argument_tools: set[str] = Field(default_factory=set)
    nested: bool = False
    pre_answer_seconds: float | None = None


class PacketRenderer:
    def __init__(self, config: RenderConfig) -> None:
        self.config = config
        self.placement = config.placement.model_copy()
        self.answer = ""
        self.reasoning = ""
        self.has_reasoned = False
        self.reasoning_active = False
        self.answer_started = False
        self.calls: dict[str, Placement] = {}
        self.citations_emitted: set[int] = set()

    def _packet(self, obj: object, placement: Placement | None = None) -> Packet:
        return Packet.model_validate(
            {"placement": placement or self.placement, "obj": obj}
        )

    def _close_reasoning(self) -> list[Packet]:
        if not self.reasoning_active:
            return []
        packets = [self._packet(ReasoningDone())]
        self.reasoning_active = False
        self.has_reasoned = True
        if self.placement.sub_turn_index is None:
            self.placement = self.placement.model_copy(
                update={"turn_index": self.placement.turn_index + 1}
            )
        else:
            self.placement = self.placement.model_copy(
                update={"sub_turn_index": self.placement.sub_turn_index + 1}
            )
        return packets

    def _thinking(self, text: str) -> list[Packet]:
        if not text:
            return []
        packets: list[Packet] = []
        if not self.reasoning_active:
            packets.append(self._packet(ReasoningStart()))
            self.reasoning_active = True
        self.reasoning += text
        packets.append(self._packet(ReasoningDelta(reasoning=text)))
        return packets

    def _answer(self, text: str) -> list[Packet]:
        if not text:
            return []
        packets = self._close_reasoning()
        if not self.answer_started:
            packets.append(
                self._packet(
                    AgentResponseStart(
                        final_documents=self.config.documents,
                        pre_answer_processing_seconds=self.config.pre_answer_seconds,
                    )
                )
            )
            self.answer_started = True
        self.answer += text
        packets.append(self._packet(AgentResponseDelta(content=text)))
        return packets

    def _content(self, text: str | None) -> list[Packet]:
        if text is not None and self.config.text_as_thinking:
            return self._thinking(text)
        if self.config.citations is None:
            return self._answer(text or "")
        packets: list[Packet] = []
        for item in self.config.citations.process_token(text):
            if isinstance(item, str):
                packets.extend(self._answer(item))
            else:
                self.citations_emitted.add(item.citation_number)
                packets.append(self._packet(item))
        return packets

    def call_placement(self, call: ToolCall) -> Placement:
        if call.id not in self.calls:
            tab = (
                self.config.placement.tab_index
                if self.config.nested
                else len(self.calls) + int(self.answer_started)
            )
            self.calls[call.id] = self.placement.model_copy(update={"tab_index": tab})
        return self.calls[call.id]

    def consume(self, event: GenerationEvent) -> list[Packet]:
        packets: list[Packet] = []
        if isinstance(event, GenerationTextEvent) and event.type == "thinking_delta":
            packets.extend(self._thinking(event.text))
        elif isinstance(event, GenerationTextEvent) and event.type == "text_delta":
            packets.extend(self._content(event.text))
        elif isinstance(event, GenerationToolCallEvent):
            call = event.tool_call
            if call.name == self.config.think_tool:
                packets.extend(
                    self._thinking(event.argument_deltas.get("reasoning", ""))
                )
                if event.type == "tool_call_end":
                    packets.extend(self._close_reasoning())
                    self.call_placement(call)
            else:
                packets.extend(self._close_reasoning())
                placement = self.call_placement(call)
                if call.name in self.config.argument_tools and event.argument_deltas:
                    packets.append(
                        self._packet(
                            ToolCallArgumentDelta(
                                tool_type=call.name,
                                argument_deltas=event.argument_deltas,
                            ),
                            placement,
                        )
                    )
        elif event.type in {"done", "error"}:
            packets.extend(self._close_reasoning())
            packets.extend(self._content(None))
            if (
                not self.answer.strip()
                and event.message.text.strip()
                and not event.message.tool_calls
                and not self.config.text_as_thinking
            ):
                packets.extend(self._answer(event.message.text))
            if event.type == "done" and self.config.mode == "report":
                packets.append(
                    self._packet(
                        IntermediateReportCitedDocs(
                            cited_docs=list(
                                self.config.citations.get_seen_citations().values()
                            )
                            if self.config.citations
                            else []
                        )
                    )
                )
                packets.append(self._packet(SectionEnd()))
        return self._project(packets)

    def _project(self, packets: list[Packet]) -> list[Packet]:
        result: list[Packet] = []
        for packet in packets:
            obj = packet.obj
            mode = self.config.mode
            if isinstance(obj, AgentResponseStart):
                if mode in {"silent", "coding_thinking"}:
                    continue
                if mode == "plan":
                    obj = DeepResearchPlanStart()
                elif mode == "report":
                    obj = IntermediateReportStart()
            elif isinstance(obj, AgentResponseDelta):
                if mode == "silent":
                    continue
                if mode == "plan":
                    obj = DeepResearchPlanDelta(content=obj.content)
                elif mode == "report":
                    obj = IntermediateReportDelta(content=obj.content)
                elif mode == "coding_thinking":
                    obj = CodingAgentThinkingDelta(content=obj.content)
            placement = (
                self.config.placement
                if mode in {"report", "silent"}
                else packet.placement
            )
            result.append(Packet(placement=placement, obj=obj))
        return result
