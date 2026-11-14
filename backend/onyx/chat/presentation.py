"""Attach chat metadata to agent output and build saved response summaries."""

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from pydantic import BaseModel

from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    InputEndedEvent,
    InputRequiredEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolResultAmendedEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.models import (
    AgentInfo,
    ExecutionStatus,
    InputMessageMetadata,
    InputSource,
    RunFailure,
    RunFailureKind,
    RunState,
    RunStatus,
)
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageMetadata,
    ChatResponseSnapshot,
    CitationMode,
    MessageRendering,
    PresentationMode,
    ResponseRecord,
    SavedToolApproval,
    ToolHistorySnapshot,
    ToolReplayData,
)
from onyx.chat.renderer import (
    HIDDEN_TOOLS,
    MessageRenderer,
    ResponseLayout,
    ToolRenderer,
    approval_outcome,
    tool_renderer,
)
from onyx.chat.response import response_record, tool_arguments_for_display
from onyx.chat.tool_approvals import TOOL_APPROVAL_TIMEOUT, ended_answer
from onyx.chat.tool_results import (
    restored_result_details,
    tool_result_parts,
    tool_result_sources,
)
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchMessageMetadata, ResearchPhase
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage, UserMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    ToolApprovalRequest,
    ToolApprovalResolved,
    UserMessagePacket,
)
from onyx.tools.constants import SEND_MESSAGE_TOOL_NAME, SPAWN_AGENT_TOOL_NAME
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    LlmPythonExecutionResult,
    ToolCallInfo,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NO_APPROVALS: Mapping[tuple[str, str], Sequence[SavedToolApproval]] = MappingProxyType(
    {}
)


def _message_identity(message: AssistantMessage) -> str:
    if not message.id:
        raise ValueError("Accepted response message has no identity")
    return message.id


def _collect_tool_history(
    snapshot: RunState,
    tool_ids: Mapping[str, int | None],
    initial_citations: CitationMapping | None = None,
    *,
    include_parent: bool = False,
) -> ToolHistorySnapshot:
    """Project completed and interrupted operations from one execution tree.

    `tool_ids` names the application tools to record, with their tool row ids; a
    tool without a row maps to None. Calls of other tools are skipped.
    """
    records: list[ToolCallInfo] = []
    documents: dict[str, SearchDoc] = {}
    citations = DynamicCitationProcessor(citation_mode=CitationMode.HYPERLINK)
    citations.update_citation_mapping(initial_citations or {})
    for step_index, step in enumerate(snapshot.steps):
        message = step.message
        documents.update(message_documents(message.metadata))
        if isinstance(message.metadata, (ChatMessageMetadata, ResearchMessageMetadata)):
            citations.update_citation_mapping(
                message.metadata.sources, update_duplicate_keys=True
            )
        for index, call in enumerate(message.tool_calls):
            if call.name not in tool_ids:
                continue
            execution = step.tools.get(call.id)
            result = execution.result if execution is not None else None
            records.append(
                _tool_record(
                    tool_ids[call.name],
                    message,
                    result,
                    call,
                    snapshot,
                    step_index,
                    index,
                    include_parent=include_parent,
                )
            )
            sources = tool_result_sources(result.details) if result else None
            if sources is None:
                continue
            for document in sources.documents:
                documents.setdefault(document.document_id, document)
            citations.update_citation_mapping(sources.citations)
    for child in snapshot.child_runs:
        child_history = _collect_tool_history(child, tool_ids, include_parent=True)
        records.extend(child_history.tool_calls)
        documents.update(child_history.all_search_docs)
    return ToolHistorySnapshot(
        tool_calls=records,
        all_search_docs=documents,
        citation_to_doc=citations.citation_to_doc,
    )


def _tool_record(
    tool_id: int | None,
    output: AssistantMessage,
    tool_response: ToolResultMessage | None,
    tool_call: ToolCall,
    snapshot: RunState,
    turn: int,
    index: int,
    *,
    include_parent: bool,
) -> ToolCallInfo:
    data = tool_response.details if tool_response else None
    sources = tool_result_sources(data)
    # Artifacts of nested calls belong to the call that made them.
    parts = (
        [part.details for part in tool_result_parts(tool_response)]
        if tool_response
        else []
    )
    generated_images = [
        image
        for part in parts
        if isinstance(part, FinalImageGenerationResponse)
        for image in part.generated_images
    ] or None
    generated_files = [
        file
        for part in parts
        if isinstance(part, LlmPythonExecutionResult)
        for file in part.generated_files
    ] or None
    # Custom tools save image/CSV blobs and return their ids.
    generated_file_ids = [
        file_id
        for part in parts
        if isinstance(part, CustomToolCallSummary)
        and isinstance(part.tool_result, CustomToolUserFileSnapshot)
        for file_id in part.tool_result.file_ids
    ] or None

    return ToolCallInfo(
        message_id=_message_identity(output),
        parent_message_id=snapshot.parent_message_id if include_parent else None,
        parent_tool_call_id=snapshot.parent_tool_call_id if include_parent else None,
        turn_index=turn,
        tab_index=index,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
        tool_id=tool_id,
        reasoning_tokens=output.thinking,  # Calls from one assistant message share its thinking.
        tool_call_arguments=tool_arguments_for_display(tool_call),
        tool_call_response=tool_response.text if tool_response else "",
        search_docs=sources.displayed if sources is not None else None,
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
    if isinstance(metadata, MessageRendering):
        return metadata.model_copy(deep=True)
    presentation = MessageRendering(
        mode=PresentationMode.CODING_THINKING
        if parent_tool_name == CODING_AGENT_TOOL_NAME
        else PresentationMode.ANSWER,
        think_tool=THINK_TOOL_NAME
        if parent_tool_name == CODING_AGENT_TOOL_NAME
        else None,
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
    tool_ids: Mapping[str, int | None],
    initial_citations: CitationMapping | None = None,
    registrations: Sequence[AgentInfo] = (),
) -> ChatResponseSnapshot:
    """Build saved output from a snapshot, independently of live packet delivery.

    Message conversion shares citation and text handling with the live stream, so saved
    answers match streamed answers. Canonical content survives display failures.
    """
    record = response_record(snapshot, registrations)
    response = ChatResponseSnapshot(
        answer=record.steps[record.answer_step_index].message.text
        if record.answer_step_index is not None
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
        return _project_response_display(snapshot, response)
    except Exception:
        logger.exception("Could not format accepted response: %s", snapshot.run_id)
        return response.model_copy(
            update={
                "error": "Response formatting failed. The accepted content has been retained.",
            }
        )


def _project_response_display(
    snapshot: RunState, response: ChatResponseSnapshot
) -> ChatResponseSnapshot:
    presentation: dict[str, MessageRendering] = {}
    record = response.response
    if record is None:
        raise ValueError("Saved response content is required for display projection")
    pending: list[tuple[RunState, str | None]] = [(snapshot, None)]
    while pending:
        node, parent_tool_name = pending.pop()
        call_names: dict[tuple[str, str], str] = {}
        for step_index, step in enumerate(node.steps):
            message = step.message
            message_id = _message_identity(message)
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
                ResponseLayout(),
            )
            is_answer = step_index == node.answer_step_index
            renderer.complete(message)
            if not is_answer and snapshot.status == RunStatus.COMPLETE:
                continue
            response = response.model_copy(
                update={
                    "answer": renderer.answer,
                    "reasoning": renderer.reasoning,
                    "citation_info": renderer.citations,
                    "top_documents": renderer.documents or response.top_documents,
                    "pre_answer_processing_time": setting.pre_answer_seconds
                    if renderer.answer_started
                    else response.pre_answer_processing_time,
                    "is_clarification": setting.is_clarification
                    and step.generation_status == ExecutionStatus.COMPLETE
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


def user_message_packets(
    messages: Sequence[UserMessage],
    layout: ResponseLayout,
    parent: Placement | None,
) -> list[Packet]:
    packets: list[Packet] = []
    for message in messages:
        if (
            not isinstance(message.metadata, InputMessageMetadata)
            or message.metadata.source != InputSource.HUMAN
        ):
            continue
        if message.id is None:
            raise ValueError("Accepted user message has no identity")
        packets.append(
            Packet(
                placement=layout.next_section(parent),
                obj=UserMessagePacket(id=message.id, message=message.text),
            )
        )
    return packets


class ResponsePresenter:
    """Translate SDK events into chat packets, with child output inside tool tabs."""

    def __init__(
        self,
        emitter: Emitter,
        *,
        tool_ids: Mapping[str, int | None] | None = None,
        display_names: Mapping[str, str] | None = None,
    ) -> None:
        self.tool_ids = tool_ids or {}
        # Tool display names by call name, for approval requests of calls that
        # a tool makes for the model.
        self.display_names = display_names or {}
        self.emitter = emitter
        self.layout = ResponseLayout()
        self.renderers: dict[str, MessageRenderer] = {}
        self.tools: dict[tuple[str, str, str], ToolRenderer] = {}

    def consume(self, event: AgentEvent) -> None:
        output: list[Packet] = []
        parent = self.tools.get(
            (
                event.parent_run_id or "",
                event.parent_message_id or "",
                event.parent_tool_call_id or "",
            )
        )
        if isinstance(event, MessageStartEvent):
            output = user_message_packets(
                event.input_messages, self.layout, parent.placement if parent else None
            )
            if event.parent_run_id is None:
                self.emitter.llm_step_started()
            if parent is not None:
                parent.has_child_output = True
            self.renderers[event.run_id] = MessageRenderer(
                message_presentation(
                    event.metadata,
                    parent_tool_name=parent.call.name if parent else None,
                ),
                message_documents(event.metadata),
                self.layout,
                parent.placement if parent else None,
            )
        elif isinstance(event, MessageUpdateEvent):
            output = self.renderers[event.run_id].consume(event.generation_event)
        elif isinstance(event, MessageEndEvent):
            renderer = self.renderers[event.run_id]
            output = renderer.complete(event.message)
            calls = [
                call
                for call in event.message.tool_calls
                if call.name != renderer.settings.think_tool
                and call.name not in HIDDEN_TOOLS
            ]
            for call in calls:
                tool_placement = renderer.tool_placement(call.id)
                self.tools[(event.run_id, event.message_id, call.id)] = tool_renderer(
                    call,
                    tool_placement,
                    self.tool_ids.get(call.name),
                )
        elif isinstance(
            event,
            (
                ToolStartEvent,
                ToolUpdateEvent,
                ToolEndEvent,
                InputRequiredEvent,
                InputEndedEvent,
            ),
        ):
            tool = self.tools.get((event.run_id, event.message_id, event.tool_call.id))
            if tool is None:
                return
            output = tool.consume(event, self.display_names)
        elif isinstance(event, ToolResultAmendedEvent):
            if event.tool_call.name in HIDDEN_TOOLS:
                return
            key = (event.run_id, event.message_id, event.tool_call.id)
            tool = self.tools.get(key)
            if tool is None:
                # A call recorded before a restore has no card in this stream;
                # the amended result renders in a new card, which later
                # amendments reuse.
                renderer = self.renderers.get(event.run_id)
                tool = self.tools[key] = tool_renderer(
                    event.tool_call,
                    renderer.tool_placement(event.tool_call.id)
                    if renderer is not None
                    else self.layout.next_section(parent.placement if parent else None),
                    self.tool_ids.get(event.tool_call.name),
                    event.display_name,
                )
            output = tool.amend(event.result)
        elif isinstance(event, AgentEndEvent):
            # The response owner reports classified failures separately.
            for key in tuple(self.tools):
                if key[0] == event.run_id:
                    output.extend(self.tools.pop(key).complete(None))
            if renderer := self.renderers.pop(event.run_id, None):
                output.extend(renderer.finish())
            if event.parent_run_id is None:
                output.append(
                    Packet(
                        placement=Placement(turn_index=0),
                        obj=overall_stop(event.outcome, event.failure),
                    )
                )
        for packet in output:
            self.emitter.emit(packet)


def overall_stop(status: RunStatus, failure: RunFailure | None) -> OverallStop:
    """How a top-level response ended: the one mapping for live, replay and Stop."""
    if status != RunStatus.CANCELLED:
        return OverallStop(stop_reason="finished")
    if failure is not None and failure.kind == RunFailureKind.DEADLINE:
        return OverallStop(stop_reason="timed_out")
    return OverallStop(stop_reason="user_cancelled")


def replay_response(
    response: ResponseRecord,
    records: Mapping[tuple[str, str], ToolReplayData],
    settings: dict[str, MessageRendering],
    documents: Mapping[str, SearchDoc],
    layout: ResponseLayout | None = None,
    parent: Placement | None = None,
    default_mode: PresentationMode = PresentationMode.ANSWER,
    *,
    approvals: Mapping[tuple[str, str], Sequence[SavedToolApproval]] = _NO_APPROVALS,
) -> list[Packet]:
    """Render saved accepted steps using detached tool records and source documents.

    `approvals` holds the response's approval requests by run ID and tool call
    ID; each shows in its call's card as the stream showed it once decided.
    The session response carries the saved message error separately. Stop packets
    close rendering; they do not classify execution success or failure.
    """
    layout = layout or ResponseLayout()
    packets: list[Packet] = []
    for step in response.steps:
        packets.extend(user_message_packets(step.input_messages, layout, parent))
        message = step.message
        message_id = _message_identity(message)
        setting = settings.get(message_id, MessageRendering(mode=default_mode))
        renderer = MessageRenderer(setting, documents, layout, parent)
        packets.extend(renderer.complete(message))
        calls = [
            call
            for call in message.tool_calls
            if call.name not in HIDDEN_TOOLS and call.name != setting.think_tool
        ]
        if not calls:
            continue
        for call in calls:
            tool_placement = renderer.tool_placement(call.id)
            record = records.get((message_id, call.id))
            execution = step.tools.get(call.id)
            result = execution.result if execution is not None else None
            details = result.details if result is not None else None
            if (
                result is not None
                and isinstance(details, SearchDocsResponse)
                and record is not None
            ):
                # Saved document IDs support citation and source-card links.
                search = details.model_copy(update={"search_docs": record.search_docs})
                result = result.model_copy(update={"details": search})
            elif result is not None and details is not None:
                # Nested results keep documents as citation numbers; the call's
                # saved documents and the response's documents refill them.
                saved_documents = record.search_docs if record is not None else []
                restored = restored_result_details(
                    details,
                    {
                        **documents,
                        **{doc.document_id: doc for doc in saved_documents},
                    },
                )
                result = result.model_copy(update={"details": restored})
            renderer_of_call = tool_renderer(
                call,
                tool_placement,
                record.tool_id if record is not None else None,
                execution.display_name if execution is not None else None,
            )
            packets.extend(renderer_of_call.start())
            for approval in approvals.get((response.run_id, call.id), ()):
                approval_id = str(approval.id)
                packets.extend(
                    Packet(placement=tool_placement, obj=obj)
                    for obj in (
                        ToolApprovalRequest(
                            approval_id=approval_id,
                            tool_call_id=call.id,
                            tool_name=approval.tool_name,
                            display_name=approval.display_name,
                            # A call that a program made is not saved.
                            arguments=tool_arguments_for_display(call)
                            if approval.tool_name == call.name
                            else {},
                            expires_at=approval.created_at + TOOL_APPROVAL_TIMEOUT,
                        ),
                        ToolApprovalResolved(
                            approval_id=approval_id,
                            outcome=approval_outcome(ended_answer(approval)),
                        ),
                    )
                )
            for child in response.child_runs:
                # Agent tools start background runs, whose output arrives separately.
                if (
                    call.name in (SPAWN_AGENT_TOOL_NAME, SEND_MESSAGE_TOOL_NAME)
                    or child.parent_message_id != message_id
                    or child.parent_tool_call_id != call.id
                ):
                    continue
                renderer_of_call.has_child_output = True
                child_mode = (
                    PresentationMode.CODING_THINKING
                    if call.name == CODING_AGENT_TOOL_NAME
                    else PresentationMode.ANSWER
                )
                packets.extend(
                    replay_response(
                        child,
                        records,
                        settings,
                        documents,
                        layout,
                        tool_placement,
                        child_mode,
                        approvals=approvals,
                    )
                )
            packets.extend(renderer_of_call.complete(result))
    if response.parent_run_id is None:
        packets.append(
            Packet(
                placement=Placement(turn_index=0),
                obj=overall_stop(response.status, response.failure),
            )
        )
    return packets
