"""Format model text and citations into public items and direct text deltas."""

from collections.abc import Mapping

from onyx.agents.transcript import RunStatus
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import MessageRendering, PresentationMode
from onyx.chat.response_items import (
    ResponseGeneration,
    ResponseItem,
    ResponseText,
    messages_from_items,
)
from onyx.chat.response_items import (
    TextPurpose as ResponseTextPurpose,
)
from onyx.context.search.models import SearchDoc
from onyx.llm.models import (
    AssistantMessage,
    GenerationErrorEvent,
    GenerationEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallStartEvent,
)
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    ItemDelta,
    ItemUpdate,
    Packet,
    PacketIdentity,
    ReasoningItem,
    TextDelta,
    TextItem,
    TextPurpose,
    ToolArgumentsDelta,
    ToolItem,
    ToolStatus,
)


class MessageRenderer:
    """Keep formatted text for completion; publish new text without reconstructing deltas."""

    def __init__(
        self,
        settings: MessageRendering,
        documents: Mapping[str, SearchDoc],
        identity: PacketIdentity,
    ) -> None:
        self.documents = documents
        self.settings = settings
        self.identity = identity
        self.citation_processor = (
            DynamicCitationProcessor(citation_mode=settings.citation_mode)
            if settings.citation_mode is not None
            else None
        )
        if self.citation_processor:
            self.citation_processor.update_citation_mapping(
                {
                    number: documents[doc_id]
                    for number, doc_id in settings.citation_documents.items()
                    if doc_id in documents
                }
            )
        purpose = {
            PresentationMode.ANSWER: TextPurpose.ANSWER,
            PresentationMode.PLAN: TextPurpose.PLAN,
            PresentationMode.REPORT: TextPurpose.REPORT,
            PresentationMode.CODING_THINKING: TextPurpose.COMMENTARY,
            PresentationMode.SILENT: TextPurpose.COMMENTARY,
        }[settings.mode]
        self.text = TextItem(
            purpose=purpose,
            documents=[
                documents[doc_id]
                for doc_id in settings.document_ids
                if doc_id in documents
            ],
            pre_answer_seconds=settings.pre_answer_seconds,
        )
        self.thinking = ReasoningItem()
        self._started: set[str] = set()
        self._tool_calls: set[str] = set()
        self._finished = False

    @property
    def answer(self) -> str:
        return self.text.text

    @property
    def reasoning(self) -> str:
        return self.thinking.text

    @property
    def answer_started(self) -> bool:
        return "answer" in self._started

    def _packet(
        self, obj: ItemUpdate | ItemDelta, part: str, tool_call_id: str | None = None
    ) -> Packet:
        return Packet(
            identity=self.identity.model_copy(
                update={"part_id": part, "tool_call_id": tool_call_id}
            ),
            obj=obj,
        )

    def _append(
        self,
        text: str,
        *,
        thinking: bool = False,
        citations: list[CitationInfo] | None = None,
    ) -> list[Packet]:
        if not text and not citations:
            return []
        if self.settings.mode == PresentationMode.SILENT:
            return []
        part = "reasoning" if thinking else "answer"
        item = self.thinking if thinking else self.text
        packets: list[Packet] = []
        if part not in self._started:
            packets.append(
                self._packet(ItemUpdate(item=item.model_copy(deep=True)), part)
            )
            self._started.add(part)
        item.text += text
        if not thinking and citations:
            self.text.citations.extend(citations)
        packets.append(
            self._packet(
                ItemDelta(delta=TextDelta(text=text, citations=citations or [])), part
            )
        )
        return packets

    def _content(self, text: str | None) -> list[Packet]:
        if self.settings.text_as_thinking:
            return self._append(text or "", thinking=True)
        if self.citation_processor is None:
            return self._append(text or "")
        packets: list[Packet] = []
        for value in self.citation_processor.process_token(text):
            packets.extend(
                self._append(value)
                if isinstance(value, str)
                else self._append("", citations=[value])
            )
        return packets

    def consume(self, event: GenerationEvent) -> list[Packet]:
        if isinstance(event, TextDeltaEvent):
            return self._content(event.text)
        if isinstance(event, ThinkingDeltaEvent):
            return self._append(event.text, thinking=True)
        if isinstance(event, (ToolCallStartEvent, ToolCallDeltaEvent)):
            call = event.tool_call
            if call.name == self.settings.think_tool:
                return self._append(
                    event.argument_deltas.get("reasoning", ""), thinking=True
                )
            packets = []
            if call.id not in self._tool_calls:
                packets.append(
                    self._packet(
                        ItemUpdate(
                            item=ToolItem(name=call.name, status=ToolStatus.PENDING)
                        ),
                        "tool",
                        call.id,
                    )
                )
                self._tool_calls.add(call.id)
            arguments = {
                key: value
                for key, value in event.argument_deltas.items()
                if key != "requestBody"
            }
            if arguments:
                packets.append(
                    self._packet(
                        ItemDelta(
                            delta=ToolArgumentsDelta(
                                name=call.name, arguments=arguments
                            )
                        ),
                        "tool",
                        call.id,
                    )
                )
            return packets
        if isinstance(event, GenerationErrorEvent):
            return self.complete(event.message, RunStatus.ERROR)
        return []

    def complete(
        self,
        message: AssistantMessage,
        status: RunStatus = RunStatus.COMPLETE,
        *,
        purpose: TextPurpose | None = None,
    ) -> list[Packet]:
        """Replace streamed previews with the accepted message, including nonstreaming output."""
        complete = MessageRenderer(self.settings, self.documents, self.identity)
        for block in message.content:
            if isinstance(block, TextContent):
                complete._content(block.text)
            elif isinstance(block, ThinkingContent):
                complete._append(block.text, thinking=True)
            elif block.name == self.settings.think_tool:
                reasoning = block.arguments.get("reasoning")
                if isinstance(reasoning, str):
                    complete._append(reasoning, thinking=True)
        if message.tool_calls and complete.text.purpose == TextPurpose.ANSWER:
            complete.text.purpose = TextPurpose.COMMENTARY
        if purpose is not None:
            complete.text.purpose = purpose
        complete._content(None)
        if message.text and not complete.text.text and not complete.thinking.text:
            complete._append(message.text)
        complete._started.update(self._started)
        packets = [
            packet
            for packet in complete.finish(status)
            if isinstance(packet.obj, ItemUpdate)
        ]
        self.text = complete.text
        self.thinking = complete.thinking
        self._started = complete._started
        self._finished = True
        for call in message.tool_calls:
            if call.name == self.settings.think_tool:
                continue
            packets.append(
                self._packet(
                    ItemUpdate(
                        item=ToolItem(
                            name=call.name,
                            arguments={
                                key: value
                                for key, value in call.arguments.items()
                                if key != "requestBody"
                            },
                            status=ToolStatus.PENDING
                            if status == RunStatus.COMPLETE
                            else ToolStatus(status),
                        )
                    ),
                    "tool",
                    call.id,
                )
            )
        return packets

    def saved(self, items: list[ResponseItem]) -> list[Packet]:
        """Format complete stored content with the same citation and purpose rules."""
        boundary = items[0].content
        if not isinstance(boundary, ResponseGeneration):
            raise ValueError("Response has no generation boundary")
        message = messages_from_items(items)[0]
        if not isinstance(message, AssistantMessage):
            raise ValueError("Response must begin with an assistant message")
        purpose = None
        if self.text.purpose == TextPurpose.ANSWER:
            purpose = (
                TextPurpose.ANSWER
                if any(
                    isinstance(item.content, ResponseText)
                    and item.content.purpose == ResponseTextPurpose.ANSWER
                    for item in items
                )
                or (
                    boundary.outcome.status in {RunStatus.CANCELLED, RunStatus.ERROR}
                    and not message.tool_calls
                )
                else TextPurpose.COMMENTARY
            )
        return [
            packet
            for packet in self.complete(
                message, boundary.outcome.status, purpose=purpose
            )
            if isinstance(packet.obj, ItemUpdate)
            and not isinstance(packet.obj.item, ToolItem)
        ]

    def finish(self, status: RunStatus) -> list[Packet]:
        if self._finished:
            return []
        self._finished = True
        if self._tool_calls and self.text.purpose == TextPurpose.ANSWER:
            self.text.purpose = TextPurpose.COMMENTARY
        packets = self._content(None)
        for part, item in (("reasoning", self.thinking), ("answer", self.text)):
            if part in self._started:
                item.status = status
                packets.append(
                    self._packet(ItemUpdate(item=item.model_copy(deep=True)), part)
                )
        return packets
