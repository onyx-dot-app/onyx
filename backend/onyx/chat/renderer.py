"""Project semantic generation events into Onyx packets without model or storage I/O."""

from pydantic import BaseModel, ConfigDict, Field

from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import PresentationMode
from onyx.context.search.models import SearchDoc
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationTextEvent,
    GenerationToolCallEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCallDeltaEvent,
)
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
    PacketIdentity,
    PacketObj,
    ReasoningDelta,
    ReasoningDone,
    ReasoningStart,
    SectionEnd,
    ToolCallArgumentDelta,
)


class RenderConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    citations: DynamicCitationProcessor | None = None
    documents: list[SearchDoc] | None = None
    mode: PresentationMode = PresentationMode.ANSWER
    text_as_thinking: bool = False
    think_tool: str | None = None
    argument_tools: set[str] = Field(default_factory=set)
    pre_answer_seconds: float | None = None


class PacketRenderer:
    def __init__(self, config: RenderConfig, identity: PacketIdentity) -> None:
        self.config = config
        self.identity = identity
        self.answer = ""
        self.reasoning = ""
        self.has_reasoned = False
        self.reasoning_active = False
        self.answer_started = False
        self.citations_emitted: set[int] = set()

    def _packet(
        self,
        obj: PacketObj,
        *,
        part_id: str = "answer",
        tool_call_id: str | None = None,
    ) -> Packet:
        return Packet(
            identity=self.identity.model_copy(
                update={"part_id": part_id, "tool_call_id": tool_call_id}
            ),
            obj=obj,
        )

    def _close_reasoning(self) -> list[Packet]:
        if not self.reasoning_active:
            return []
        packets = [self._packet(ReasoningDone(), part_id="reasoning")]
        self.reasoning_active = False
        self.has_reasoned = True
        return packets

    def _thinking(self, text: str) -> list[Packet]:
        if not text:
            return []
        packets: list[Packet] = []
        if not self.reasoning_active:
            packets.append(self._packet(ReasoningStart(), part_id="reasoning"))
            self.reasoning_active = True
        self.reasoning += text
        packets.append(
            self._packet(ReasoningDelta(reasoning=text), part_id="reasoning")
        )
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
            else:
                packets.extend(self._close_reasoning())
                if call.name in self.config.argument_tools and event.argument_deltas:
                    packets.append(
                        self._packet(
                            ToolCallArgumentDelta(
                                tool_type=call.name,
                                argument_deltas=event.argument_deltas,
                            ),
                            tool_call_id=call.id,
                            part_id="tool",
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
            result.append(packet.model_copy(update={"obj": obj}))
        return result


def render_message(
    renderer: PacketRenderer, message: AssistantMessage, *, complete: bool
) -> list[Packet]:
    """Project a recorded prefix through the same renderer used for live updates."""
    packets: list[Packet] = []
    for index, content in enumerate(message.content):
        if isinstance(content, TextContent):
            event = TextDeltaEvent(
                message=message, content_index=index, text=content.text
            )
        elif isinstance(content, ThinkingContent):
            event = ThinkingDeltaEvent(
                message=message, content_index=index, text=content.text
            )
        else:
            event = ToolCallDeltaEvent(
                message=message,
                content_index=index,
                tool_call=content,
                argument_deltas={
                    key: value
                    for key, value in content.arguments.items()
                    if isinstance(value, str)
                },
            )
        packets.extend(renderer.consume(event))
    if complete:
        packets.extend(renderer.consume(GenerationDoneEvent(message=message)))
    elif message.stop_reason == "error":
        packets.extend(renderer.consume(GenerationErrorEvent(message=message)))
    return packets
