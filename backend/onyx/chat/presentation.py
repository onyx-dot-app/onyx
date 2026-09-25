"""Attach chat metadata to agent output and build saved response summaries."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, TypeAdapter

from onyx.agents.coordination import AgentCoordinator, AgentInfo
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.items import ResponseText, TextPurpose, group_response_items_by_step
from onyx.agents.models import RunState
from onyx.agents.transcript import RunStatus
from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageMetadata,
    ChatResponseSnapshot,
    CitationMode,
    MessageRendering,
    PresentationMode,
)
from onyx.chat.renderer import MessageRenderer
from onyx.chat.response import response_record
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.context.search.models import SearchDoc
from onyx.deep_research.models import ResearchMessageMetadata, ResearchPhase
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.models import AssistantMessage
from onyx.server.query_and_chat.streaming_models import (
    ItemDelta,
    ItemUpdate,
    OverallStop,
    Packet,
    PacketIdentity,
    RunUpdate,
    ToolItem,
    ToolMetadata,
    ToolOutputUpdate,
    ToolStatus,
)
from onyx.server.query_and_chat.streaming_models import (
    TextPurpose as DisplayTextPurpose,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def message_presentation(
    metadata: BaseModel | None,
    *,
    parent_tool_name: str | None = None,
) -> MessageRendering:
    """Resolve feature metadata into display settings retained for history replay."""
    presentation = MessageRendering(
        mode=PresentationMode.CODING_THINKING
        if parent_tool_name == CODING_AGENT_TOOL_NAME
        else PresentationMode.ANSWER,
    )
    if isinstance(metadata, ChatMessageMetadata):
        presentation.citation_mode = (
            CitationMode.HYPERLINK
            if metadata.include_citations
            else CitationMode.REMOVE
        )
        presentation.citation_documents = {
            number: doc.document_id for number, doc in metadata.sources.items()
        }
        presentation.document_ids = [doc.document_id for doc in metadata.documents]
        presentation.pre_answer_seconds = metadata.elapsed_seconds
    elif isinstance(metadata, ResearchMessageMetadata):
        presentation.pre_answer_seconds = metadata.elapsed_seconds
        presentation.is_clarification = metadata.phase == ResearchPhase.CLARIFICATION
        if metadata.phase == ResearchPhase.PLANNING:
            presentation.mode = PresentationMode.PLAN
        elif metadata.phase == ResearchPhase.RESEARCH:
            presentation.text_as_thinking = True
            presentation.think_tool = (
                THINK_TOOL_NAME if not metadata.is_reasoning_model else None
            )
        elif metadata.phase == ResearchPhase.REPORT:
            presentation.mode = (
                PresentationMode.REPORT
                if metadata.is_intermediate
                else PresentationMode.ANSWER
            )
            presentation.citation_mode = (
                CitationMode.KEEP_MARKERS
                if metadata.is_intermediate
                else CitationMode.HYPERLINK
            )
            presentation.citation_documents = {
                number: doc.document_id for number, doc in metadata.sources.items()
            }
            presentation.document_ids = [
                doc.document_id for doc in metadata.sources.values()
            ]
    return presentation


def message_documents(metadata: BaseModel | None) -> dict[str, SearchDoc]:
    if isinstance(metadata, ChatMessageMetadata):
        return {
            doc.document_id: doc
            for doc in [*metadata.sources.values(), *metadata.documents]
        }
    if isinstance(metadata, ResearchMessageMetadata):
        return {doc.document_id: doc for doc in metadata.sources.values()}
    return {}


def project_response(
    snapshot: RunState,
    *,
    response_id: int,
    tool_ids: Mapping[str, int],
    initial_citations: CitationMapping | None = None,
    registrations: Sequence[AgentInfo] = (),
) -> ChatResponseSnapshot:
    """Build saved output from a snapshot, independently of live packet delivery.

    Message conversion shares citation and text handling with the live stream, so saved
    answers match streamed answers. Canonical content survives display failures.
    """
    record = response_record(snapshot, registrations)
    response = ChatResponseSnapshot(
        answer="".join(
            item.content.text
            for item in snapshot.items
            if isinstance(item.content, ResponseText)
            and item.content.purpose == TextPurpose.ANSWER
        ),
        reasoning=None,
        request_params=snapshot.request_params,
        citation_to_doc={},
        tool_calls=[],
        is_clarification=False,
        all_search_docs={},
        pre_answer_processing_time=None,
        response=record,
        cancelled=snapshot.status == RunStatus.CANCELLED,
        delivery_failed=False,
    )
    try:
        artifacts = project_tool_artifacts(snapshot, tool_ids, initial_citations)
        response = response.model_copy(
            update={
                "citation_to_doc": artifacts.citation_to_doc,
                "tool_calls": artifacts.tool_calls,
                "all_search_docs": artifacts.all_search_docs,
            }
        )
    except Exception:
        logger.exception("Could not project response artifacts: %s", snapshot.run_id)
    try:
        return _project_response_display(snapshot, response_id, response)
    except Exception:
        logger.exception("Could not format accepted response: %s", snapshot.run_id)
        return response.model_copy(
            update={
                "error": "Response formatting failed. The accepted content has been retained.",
            }
        )


def _project_response_display(
    snapshot: RunState, response_id: int, response: ChatResponseSnapshot
) -> ChatResponseSnapshot:
    presentation: dict[str, MessageRendering] = {}
    pending: list[tuple[RunState, str | None]] = [(snapshot, None)]
    while pending:
        node, parent_tool_name = pending.pop()
        call_names: dict[tuple[str, str], str] = {}
        items_by_step = group_response_items_by_step(node.items)
        for operation in node.operations:
            if operation.tool_call_id is not None:
                continue
            message = node.messages[operation.message_index]
            if not isinstance(message, AssistantMessage):
                raise ValueError("Message operation has invalid output")
            message_id = message.id or f"{node.run_id}:{operation.step_index}"
            call_names.update(
                {(message_id, call.id): call.name for call in message.tool_calls}
            )
            setting = message_presentation(
                message.metadata,
                parent_tool_name=parent_tool_name,
            )
            presentation[message_id] = setting
            if node is not snapshot or setting.mode != PresentationMode.ANSWER:
                continue
            renderer = MessageRenderer(
                setting,
                message_documents(message.metadata),
                PacketIdentity(
                    response_id=response_id,
                    run_id=node.run_id,
                    message_id=message_id,
                ),
            )
            generation_items = items_by_step[operation.step_index]
            renderer.saved(generation_items)
            is_answer = any(
                isinstance(item.content, ResponseText)
                and item.content.purpose == TextPurpose.ANSWER
                for item in generation_items
            )
            if not is_answer and snapshot.status == RunStatus.COMPLETE:
                continue
            response = response.model_copy(
                update={
                    "answer": renderer.answer,
                    "reasoning": renderer.reasoning,
                    "citation_info": response.citation_info + renderer.text.citations,
                    "top_documents": renderer.text.documents or response.top_documents,
                    "pre_answer_processing_time": setting.pre_answer_seconds
                    if renderer.answer_started
                    else response.pre_answer_processing_time,
                    "is_clarification": setting.is_clarification
                    and operation.status == RunStatus.COMPLETE
                    and not message.tool_calls,
                }
            )
        pending.extend(
            (
                child,
                call_names.get(
                    (child.parent_message_id or "", child.parent_tool_call_id or "")
                ),
            )
            for child in node.child_runs
        )
    return response.model_copy(update={"presentation": presentation})


_TOOL_METADATA = TypeAdapter(ToolMetadata)


class ResponsePresenter:
    """Publish item updates with stable identities across root and child runs."""

    def __init__(
        self,
        emitter: Emitter,
        coordinator: AgentCoordinator | None = None,
        *,
        tool_ids: Mapping[str, int] | None = None,
    ) -> None:
        self.tool_ids = tool_ids or {}
        self.emitter = emitter
        self.coordinator = coordinator
        self.renderers: dict[str, MessageRenderer] = {}
        self.call_names: dict[tuple[str, str], str] = {}

    def _identity(self, event: AgentEvent, step_index: int) -> PacketIdentity:
        registration = (
            self.coordinator.registration(event.agent_id)
            if self.coordinator and event.agent_id is not None
            else None
        )
        return PacketIdentity(
            response_id=self.emitter.response_id,
            run_id=event.run_id,
            agent_id=event.agent_id,
            agent_path=registration.path if registration else None,
            message_id=f"{event.run_id}:{step_index}",
            parent_run_id=event.parent_run_id,
            parent_message_id=event.parent_message_id,
            parent_tool_call_id=event.parent_tool_call_id,
        )

    def consume(self, event: AgentEvent) -> None:
        if isinstance(event, MessageStartEvent):
            previous = self.renderers.get(event.run_id)
            if (
                previous
                and previous.answer_started
                and previous.text.purpose == DisplayTextPurpose.ANSWER
            ):
                previous.text.purpose = DisplayTextPurpose.COMMENTARY
                self.emitter.emit(
                    Packet(
                        identity=previous.identity,
                        obj=ItemUpdate(item=previous.text.model_copy(deep=True)),
                    )
                )
            setting = message_presentation(
                event.metadata,
                parent_tool_name=self.call_names.get(
                    (event.parent_message_id or "", event.parent_tool_call_id or "")
                ),
            )
            self.renderers[event.run_id] = MessageRenderer(
                setting,
                message_documents(event.metadata),
                self._identity(event, event.step_index),
            )
        elif isinstance(event, MessageUpdateEvent):
            for packet in self.renderers[event.run_id].consume(event.generation_event):
                self.emitter.emit(packet)
        elif isinstance(event, MessageEndEvent):
            for packet in self.renderers[event.run_id].complete(event.message):
                self.emitter.emit(packet)
        elif isinstance(event, (ToolStartEvent, ToolUpdateEvent, ToolEndEvent)):
            identity = self._identity(event, event.step_index).model_copy(
                update={"tool_call_id": event.tool_call.id, "part_id": "tool"}
            )
            key = (identity.message_id, event.tool_call.id)
            if isinstance(event, ToolStartEvent):
                self.call_names[key] = event.tool_call.name
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=ItemUpdate(
                            item=ToolItem(
                                name=event.tool_call.name,
                                tool_id=self.tool_ids.get(event.tool_call.name),
                                arguments={
                                    key: value
                                    for key, value in event.tool_call.arguments.items()
                                    if key != "requestBody"
                                },
                            )
                        ),
                    )
                )
            elif isinstance(event, ToolUpdateEvent):
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=ItemDelta(
                            delta=ToolOutputUpdate(
                                output=event.progress.content or None,
                                metadata=_TOOL_METADATA.validate_python(
                                    event.progress.details.model_dump()
                                )
                                if event.progress.details is not None
                                else None,
                            )
                        ),
                    )
                )
            else:
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=ItemUpdate(
                            item=ToolItem(
                                name=event.tool_call.name,
                                tool_id=self.tool_ids.get(event.tool_call.name),
                                arguments={
                                    key: value
                                    for key, value in event.tool_call.arguments.items()
                                    if key != "requestBody"
                                },
                                status=ToolStatus.ERROR
                                if event.result.is_error
                                else ToolStatus.COMPLETE,
                                output=event.result.text
                                if event.result.details is None
                                else "",
                                metadata=_TOOL_METADATA.validate_python(
                                    event.result.details.model_dump()
                                )
                                if event.result.details is not None
                                else None,
                            )
                        ),
                    )
                )
        elif isinstance(event, (AgentStartEvent, AgentEndEvent)):
            identity = self._identity(event, 0).model_copy(update={"part_id": "run"})
            status = (
                event.outcome if isinstance(event, AgentEndEvent) else RunStatus.RUNNING
            )
            if isinstance(event, AgentEndEvent):
                if renderer := self.renderers.pop(event.run_id, None):
                    if (
                        event.answer_message_id == renderer.identity.message_id
                        and renderer.text.purpose == DisplayTextPurpose.COMMENTARY
                    ):
                        renderer.text.purpose = DisplayTextPurpose.ANSWER
                        self.emitter.emit(
                            Packet(
                                identity=renderer.identity,
                                obj=ItemUpdate(
                                    item=renderer.text.model_copy(deep=True)
                                ),
                            )
                        )
                    for packet in renderer.finish(status):
                        self.emitter.emit(packet)
            self.emitter.emit(Packet(identity=identity, obj=RunUpdate(status=status)))
            if isinstance(event, AgentEndEvent) and event.parent_run_id is None:
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=OverallStop(
                            stop_reason="user_cancelled"
                            if status == RunStatus.CANCELLED
                            else "finished"
                        ),
                    )
                )
