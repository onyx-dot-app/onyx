"""Render one generation’s response items as frontend content packets.

Handles text, reasoning, citations, and streamed tool arguments. Presentation settings
select answer, plan, report, or coding output. Live updates and saved history use the
same conversion so citation formatting and content boundaries agree.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.items import (
    ResponseGeneration,
    ResponseItem,
    ResponseReasoning,
    ResponseText,
    ResponseToolCall,
)
from onyx.agents.transcript import RunStatus
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import MessageRendering, PresentationMode
from onyx.context.search.models import SearchDoc
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
    """Resolved display settings and a citation processor for one message conversion."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    citations: DynamicCitationProcessor | None = None
    documents: list[SearchDoc] | None = None
    mode: PresentationMode = PresentationMode.ANSWER
    text_as_thinking: bool = False
    think_tool: str | None = None
    argument_tools: set[str] = Field(default_factory=set)
    pre_answer_seconds: float | None = None


def render_config(
    presentation: MessageRendering,
    documents: Mapping[str, SearchDoc],
) -> RenderConfig:
    """Resolve saved document IDs and create a fresh citation processor."""
    citations = None
    if presentation.citation_mode is not None:
        citations = DynamicCitationProcessor(citation_mode=presentation.citation_mode)
        citations.update_citation_mapping(
            {
                number: documents[doc_id]
                for number, doc_id in presentation.citation_documents.items()
                if doc_id in documents
            }
        )
    return RenderConfig(
        mode=presentation.mode,
        text_as_thinking=presentation.text_as_thinking,
        think_tool=presentation.think_tool,
        argument_tools=set(presentation.argument_tools),
        pre_answer_seconds=presentation.pre_answer_seconds,
        documents=[
            documents[doc_id]
            for doc_id in presentation.document_ids
            if doc_id in documents
        ]
        or None,
        citations=citations,
    )


class PacketRenderer:
    """Render live or saved response items for one generation into frontend packets."""

    def __init__(self, config: RenderConfig, identity: PacketIdentity) -> None:
        self.config = config
        self.identity = identity
        self.answer = ""
        self.reasoning = ""
        self.reasoning_active = False
        self.answer_started = False
        self._item_offsets: dict[str, int] = {}
        self._seen_tool_items: set[str] = set()
        self._generation_finished = False

    def consume_items(self, items: list[ResponseItem]) -> list[Packet]:
        """Render accepted item updates; offsets prevent repeated streamed content."""
        if not items:
            return []
        boundary = items[0].content
        if not isinstance(boundary, ResponseGeneration):
            raise ValueError("Rendering requires a generation boundary")
        packets: list[Packet] = []
        for item in items[1:]:
            content = item.content
            if isinstance(content, (ResponseText, ResponseReasoning)):
                text = (
                    content.text
                    if isinstance(content, ResponseText)
                    else content.content.text
                )
                offset = self._item_offsets.get(item.id, 0)
                self._item_offsets[item.id] = len(text)
                if len(text) == offset:
                    continue
                packets.extend(
                    self._content(text[offset:])
                    if isinstance(content, ResponseText)
                    else self._thinking(text[offset:])
                )
            elif isinstance(content, ResponseToolCall):
                fragments: dict[str, str] = {}
                for name, value in content.call.arguments.items():
                    if not isinstance(value, str):
                        continue
                    key = f"{item.id}:{name}"
                    offset = self._item_offsets.get(key, 0)
                    self._item_offsets[key] = len(value)
                    if len(value) > offset:
                        fragments[name] = value[offset:]
                if item.id in self._seen_tool_items and not fragments:
                    continue
                self._seen_tool_items.add(item.id)
                call = content.call
                if call.name == self.config.think_tool:
                    packets.extend(self._thinking(fragments.get("reasoning", "")))
                else:
                    packets.extend(self._close_reasoning())
                    if call.name in self.config.argument_tools and fragments:
                        packets.append(
                            self._packet(
                                ToolCallArgumentDelta(
                                    tool_type=call.name,
                                    argument_deltas=fragments,
                                ),
                                tool_call_id=call.id,
                                part_id="tool",
                            )
                        )
        if (
            boundary.outcome.status != RunStatus.RUNNING
            and not self._generation_finished
        ):
            packets.extend(self._finish_packets(boundary.outcome.status))
            if (
                not self.answer.strip()
                and not self.config.text_as_thinking
                and not any(
                    isinstance(item.content, ResponseToolCall) for item in items
                )
            ):
                text = "".join(
                    item.content.text
                    for item in items
                    if isinstance(item.content, ResponseText)
                )
                if text.strip():
                    packets.extend(self._answer(text))
        return self._apply_presentation_mode(packets)

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
                packets.append(self._packet(item))
        return packets

    def finish(self, status: RunStatus) -> list[Packet]:
        """Flush display buffers when execution ends before a generation-end event."""
        return self._apply_presentation_mode(self._finish_packets(status))

    def _finish_packets(self, status: RunStatus) -> list[Packet]:
        if self._generation_finished:
            return []
        self._generation_finished = True
        packets = self._close_reasoning()
        packets.extend(self._content(None))
        if status == RunStatus.COMPLETE and self.config.mode == PresentationMode.REPORT:
            packets.append(
                self._packet(
                    IntermediateReportCitedDocs(
                        cited_docs=list(
                            self.config.citations.get_seen_citations().values()
                        )
                        if self.config.citations
                        else [],
                    )
                )
            )
            packets.append(self._packet(SectionEnd()))
        return packets

    def _apply_presentation_mode(self, packets: list[Packet]) -> list[Packet]:
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
