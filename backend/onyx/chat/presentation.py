"""Attach chat metadata to agent output and build saved response summaries."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from onyx.agents.agent_coordination import (
    AgentCoordinator,
)
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
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentInfo, RunState
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.citation_utils import update_citation_processor_from_tool_result
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageMetadata,
    ChatResponseSnapshot,
    CitationMode,
    MessageRendering,
    PresentationMode,
    ToolHistorySnapshot,
)
from onyx.chat.renderer import MessageRenderer, build_tool_item, tool_metadata
from onyx.chat.response import response_record
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchMessageMetadata,
    ResearchPhase,
)
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage
from onyx.server.query_and_chat.streaming_models import (
    ItemDelta,
    ItemUpdate,
    OverallStop,
    Packet,
    PacketIdentity,
    RunUpdate,
    ToolOutputUpdate,
    ToolStatus,
)
from onyx.server.query_and_chat.streaming_models import (
    TextPurpose as DisplayTextPurpose,
)
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    LlmPythonExecutionResult,
    ToolCallInfo,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _saved_tool_metadata(result: ToolResultMessage) -> BaseModel | None:
    data = result.details
    if isinstance(data, SearchDocsResponse):
        # Documents are stored through the tool call's search-document relation.
        return SearchDocsResponse(
            queries=data.queries,
            sources=data.sources,
            time_filter_start=data.time_filter_start,
            time_filter_end=data.time_filter_end,
            search_docs=[],
            citation_mapping=data.citation_mapping,
        )
    return data


def _collect_tool_history(
    snapshot: RunState,
    tool_ids: Mapping[str, int],
    initial_citations: CitationMapping | None = None,
) -> ToolHistorySnapshot:
    """Project completed and interrupted operations from one execution tree."""
    records: list[ToolCallInfo] = []
    documents: dict[str, SearchDoc] = {}
    citations = DynamicCitationProcessor(citation_mode=CitationMode.HYPERLINK)
    citations.update_citation_mapping(initial_citations or {})
    for operation in snapshot.operations:
        if operation.tool_call_id is not None:
            continue
        message = snapshot.messages[operation.message_index]
        if not isinstance(message, AssistantMessage):
            raise ValueError(
                "Message operation does not reference an assistant message"
            )
        results: dict[str, ToolResultMessage] = {}
        for item in snapshot.messages[operation.message_index + 1 :]:
            if isinstance(item, AssistantMessage):
                break
            if isinstance(item, ToolResultMessage):
                results[item.tool_call_id] = item
        for index, call in enumerate(message.tool_calls):
            tool_id = tool_ids.get(call.name)
            if tool_id is None:
                continue
            result = results.get(call.id)
            records.append(
                _tool_record(
                    tool_id,
                    message,
                    result,
                    call,
                    snapshot,
                    operation.step_index,
                    index,
                )
            )
            if result is None:
                continue
            if isinstance(result.details, SearchDocsResponse):
                for document in result.details.search_docs:
                    documents.setdefault(document.document_id, document)
            if isinstance(result.details, ResearchAgentCallResult):
                citations.update_citation_mapping(result.details.citation_mapping)
                for document in result.details.citation_mapping.values():
                    documents.setdefault(document.document_id, document)
            update_citation_processor_from_tool_result(result, citations)
    for child in snapshot.child_runs:
        child_history = _collect_tool_history(child, tool_ids)
        records.extend(child_history.tool_calls)
        documents.update(child_history.all_search_docs)
    return ToolHistorySnapshot(
        tool_calls=records,
        all_search_docs=documents,
        citation_to_doc=citations.citation_to_doc,
    )


def _tool_record(
    tool_id: int,
    output: AssistantMessage,
    tool_response: ToolResultMessage | None,
    tool_call: ToolCall,
    snapshot: RunState,
    turn: int,
    index: int,
) -> ToolCallInfo:
    data = tool_response.details if tool_response else None
    search_docs = data.search_docs if isinstance(data, SearchDocsResponse) else None
    displayed_docs = (
        data.displayed_docs if isinstance(data, SearchDocsResponse) else None
    )
    generated_images = None
    if isinstance(data, FinalImageGenerationResponse):
        generated_images = data.generated_images

    generated_files = None
    if isinstance(data, LlmPythonExecutionResult):
        generated_files = data.generated_files or None

    # Custom tools save image/CSV blobs and return their ids.
    generated_file_ids = None
    if isinstance(data, CustomToolCallSummary) and isinstance(
        data.tool_result, CustomToolUserFileSnapshot
    ):
        generated_file_ids = data.tool_result.file_ids or None

    saved_metadata = _saved_tool_metadata(tool_response) if tool_response else None

    return ToolCallInfo(
        message_id=output.id or f"{snapshot.run_id}:{turn}",
        parent_message_id=snapshot.parent_message_id,
        parent_tool_call_id=snapshot.parent_tool_call_id,
        turn_index=turn,
        tab_index=index,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
        tool_id=tool_id,
        reasoning_tokens=output.thinking,  # Calls from one assistant message share its thinking.
        tool_call_arguments=tool_call.arguments,
        tool_call_response=tool_response.text if tool_response else "",
        result_metadata=saved_metadata,
        search_docs=displayed_docs or search_docs,
        generated_images=generated_images,
        generated_files=generated_files,
        generated_file_ids=generated_file_ids,
    )


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
        answer=record.messages[record.answer_message_index].text
        if record.answer_message_index is not None
        else "",
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
        tool_history = _collect_tool_history(snapshot, tool_ids, initial_citations)
        response = response.model_copy(
            update={
                "citation_to_doc": tool_history.citation_to_doc,
                "tool_calls": tool_history.tool_calls,
                "all_search_docs": tool_history.all_search_docs,
            }
        )
    except Exception:
        logger.exception("Could not collect tool history: %s", snapshot.run_id)
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
    record = response.response
    if record is None:
        raise ValueError("Saved response content is required for display projection")
    pending: list[tuple[RunState, str | None]] = [(snapshot, None)]
    while pending:
        node, parent_tool_name = pending.pop()
        call_names: dict[tuple[str, str], str] = {}
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
            is_answer = operation.message_index == node.answer_message_index
            renderer.saved(message, operation.status, is_answer=is_answer)
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

    def _identity(self, event: AgentEvent, message_id: str) -> PacketIdentity:
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
            message_id=message_id,
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
                self._identity(event, event.message_id),
            )
        elif isinstance(event, MessageUpdateEvent):
            for packet in self.renderers[event.run_id].consume(event.generation_event):
                self.emitter.emit(packet)
        elif isinstance(event, MessageEndEvent):
            for packet in self.renderers[event.run_id].complete(
                event.message, event.status
            ):
                self.emitter.emit(packet)
        elif isinstance(event, (ToolStartEvent, ToolUpdateEvent, ToolEndEvent)):
            identity = self._identity(event, event.message_id).model_copy(
                update={"tool_call_id": event.tool_call.id, "part_id": "tool"}
            )
            key = (identity.message_id, event.tool_call.id)
            if isinstance(event, ToolStartEvent):
                self.call_names[key] = event.tool_call.name
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=ItemUpdate(
                            item=build_tool_item(
                                name=event.tool_call.name,
                                tool_id=self.tool_ids.get(event.tool_call.name),
                                arguments=event.tool_call.arguments,
                                status=ToolStatus.RUNNING,
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
                                metadata=tool_metadata(event.progress.details),
                            )
                        ),
                    )
                )
            else:
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=ItemUpdate(
                            item=build_tool_item(
                                name=event.tool_call.name,
                                tool_id=self.tool_ids.get(event.tool_call.name),
                                arguments=event.tool_call.arguments,
                                status=ToolStatus.ERROR
                                if event.result.is_error
                                else ToolStatus.COMPLETE,
                                result=event.result,
                            )
                        ),
                    )
                )
        elif isinstance(event, (AgentStartEvent, AgentEndEvent)):
            identity = self._identity(event, f"{event.run_id}:0").model_copy(
                update={"part_id": "run"}
            )
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
