"""Adapt agent output to chat responses and the frontend packet contract.

ResponsePresenter routes live events across messages and child agents. project_response
builds the saved response from a run snapshot. Both use renderer for message content;
tool_progress supplies tool packets. Feature metadata selects answer, plan, or report output.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from onyx.agents.coordination import AgentCoordinator, AgentInfo
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.models import RunSnapshot
from onyx.agents.transcript import RunStatus
from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
)
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatResponseSnapshot,
    ChatStepOutput,
    MessagePresentation,
    PresentationMode,
)
from onyx.chat.renderer import PacketRenderer, render_config, render_message
from onyx.chat.tool_progress import (
    ToolProgressTracker,
    project_tool_progress,
    tool_display_progress,
)
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.context.search.models import SearchDoc
from onyx.deep_research.models import ResearchPhase, ResearchStepOutput
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.models import AssistantMessage
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    OperationStatus,
    OverallStop,
    Packet,
    PacketIdentity,
    SectionEnd,
)
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ARGUMENT_TOOLS = frozenset({BashTool.NAME, PythonTool.NAME})


def message_presentation(
    metadata: BaseModel | None,
    *,
    run_id: str,
    step_index: int,
    parent_tool_name: str | None = None,
) -> MessagePresentation:
    """Resolve feature metadata into display settings retained for history replay."""
    presentation = MessagePresentation(
        run_id=run_id,
        step_index=step_index,
        argument_tools=set(_ARGUMENT_TOOLS),
        mode=PresentationMode.CODING_THINKING
        if parent_tool_name == CODING_AGENT_TOOL_NAME
        else PresentationMode.ANSWER,
    )
    if isinstance(metadata, ChatStepOutput):
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
    elif isinstance(metadata, ResearchStepOutput):
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
    if isinstance(metadata, ChatStepOutput):
        return {
            doc.document_id: doc
            for doc in [*metadata.sources.values(), *metadata.documents]
        }
    if isinstance(metadata, ResearchStepOutput):
        return {doc.document_id: doc for doc in metadata.sources.values()}
    return {}


def project_response(
    snapshot: RunSnapshot,
    *,
    response_id: int,
    tool_ids: Mapping[str, int],
    initial_citations: CitationMapping | None = None,
    registrations: Sequence[AgentInfo] = (),
) -> ChatResponseSnapshot:
    """Build saved output from a snapshot, independently of live packet delivery.

    Message conversion shares citation and text handling with the live stream, so saved
    answers match streamed answers. Unfinished run trees omit the durable transcript.
    """
    artifacts = project_tool_artifacts(snapshot, tool_ids, initial_citations)
    transcript = snapshot.transcript()
    metadata = {info.id: info for info in registrations}
    records = [transcript]
    has_unfinished_run = False
    while records:
        record = records.pop()
        has_unfinished_run |= record.status == RunStatus.RUNNING
        if info := metadata.get(record.agent_id):
            record.agent_path = info.path
            record.agent_description = info.description
            record.restoration_config = info.restoration_config
        records.extend(record.child_runs)
    if has_unfinished_run:
        logger.warning("Omitting unfinished run transcript: %s", snapshot.run_id)
    # The root input is stored in the chat user record; child tasks remain in their records.
    transcript.input_messages.clear()
    response = ChatResponseSnapshot(
        answer=None,
        reasoning=None,
        request_params=snapshot.request_params,
        citation_to_doc=artifacts.citation_to_doc,
        tool_calls=artifacts.tool_calls,
        is_clarification=False,
        all_search_docs=artifacts.all_search_docs,
        pre_answer_processing_time=None,
        transcript=None if has_unfinished_run else transcript,
        cancelled=snapshot.status == RunStatus.CANCELLED,
        delivery_failed=False,
    )
    presentation: list[MessagePresentation] = []
    pending: list[tuple[RunSnapshot, str | None]] = [(snapshot, None)]
    while pending:
        node, parent_tool_name = pending.pop()
        call_names: dict[tuple[str, str], str] = {}
        for operation in node.operations:
            if operation.tool_call_id is not None:
                continue
            message = node.messages[operation.message_index]
            if not isinstance(message, AssistantMessage):
                raise ValueError("Message operation has invalid output")
            message_id = f"{node.run_id}:{operation.step_index}"
            call_names.update(
                {(message_id, call.id): call.name for call in message.tool_calls}
            )
            setting = message_presentation(
                message.metadata,
                run_id=node.run_id,
                step_index=operation.step_index,
                parent_tool_name=parent_tool_name,
            )
            presentation.append(setting)
            config = render_config(setting, message_documents(message.metadata))
            if node is not snapshot or config.mode != PresentationMode.ANSWER:
                continue
            renderer = PacketRenderer(
                config,
                PacketIdentity(
                    response_id=response_id,
                    run_id=node.run_id,
                    message_id=message_id,
                ),
            )
            packets = render_message(
                renderer, message, complete=operation.status == RunStatus.COMPLETE
            )
            response = response.model_copy(
                update={
                    "answer": renderer.answer,
                    "reasoning": renderer.reasoning,
                    "citation_info": response.citation_info
                    + [
                        packet.obj
                        for packet in packets
                        if isinstance(packet.obj, CitationInfo)
                    ],
                    "top_documents": config.documents
                    if renderer.answer_started and config.documents
                    else response.top_documents,
                    "pre_answer_processing_time": config.pre_answer_seconds
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


class _ActiveTool:
    def __init__(self, identity: PacketIdentity) -> None:
        self.identity = identity
        self.progress = ToolProgressTracker()


class ResponsePresenter:
    """Route live agent events into chat packets with message and parent identities.

    Each message has a PacketRenderer. Tool progress is tracked until completion so
    final results can supply fields that were not streamed.
    """

    def __init__(
        self, emitter: Emitter, coordinator: AgentCoordinator | None = None
    ) -> None:
        self.emitter = emitter
        self.coordinator = coordinator
        self.renderers: dict[str, PacketRenderer] = {}
        self.active_calls: dict[tuple[str, str], _ActiveTool] = {}
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
            setting = message_presentation(
                event.metadata,
                run_id=event.run_id,
                step_index=event.step_index,
                parent_tool_name=self.call_names.get(
                    (event.parent_message_id or "", event.parent_tool_call_id or "")
                ),
            )
            config = render_config(setting, message_documents(event.metadata))
            self.renderers[event.run_id] = PacketRenderer(
                config, self._identity(event, event.step_index)
            )
        elif isinstance(event, MessageUpdateEvent):
            for packet in self.renderers[event.run_id].consume(event.generation_event):
                self.emitter.emit(packet)
        elif isinstance(event, (ToolStartEvent, ToolUpdateEvent, ToolEndEvent)):
            identity = self._identity(event, event.step_index).model_copy(
                update={"tool_call_id": event.tool_call.id, "part_id": "tool"}
            )
            key = (identity.message_id, event.tool_call.id)
            if isinstance(event, ToolStartEvent):
                self.active_calls[key] = _ActiveTool(identity)
                self.call_names[key] = event.tool_call.name
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=OperationStatus(
                            status=RunStatus.RUNNING, tool_name=event.tool_call.name
                        ),
                    )
                )
            elif isinstance(event, ToolUpdateEvent):
                self.active_calls[key].progress.observe(event.progress)
                packet = project_tool_progress(event.progress)
                if packet is not None:
                    self.emitter.emit(Packet(identity=identity, obj=packet))
            else:
                active = self.active_calls.pop(key)
                for progress in tool_display_progress(event.tool_call, event.result):
                    remaining = active.progress.remaining(progress)
                    if remaining is None:
                        continue
                    packet = project_tool_progress(remaining)
                    if packet is not None:
                        self.emitter.emit(Packet(identity=identity, obj=packet))
                self.emitter.emit(
                    Packet(
                        identity=identity,
                        obj=OperationStatus(
                            status=RunStatus.ERROR
                            if event.result.is_error
                            else RunStatus.COMPLETE,
                            tool_name=event.tool_call.name,
                        ),
                    )
                )
                self.emitter.emit(Packet(identity=identity, obj=SectionEnd()))
        elif isinstance(event, (AgentStartEvent, AgentEndEvent)):
            identity = self._identity(event, 0).model_copy(update={"part_id": "run"})
            status = (
                event.outcome if isinstance(event, AgentEndEvent) else RunStatus.RUNNING
            )
            if isinstance(event, AgentEndEvent):
                for key, active in list(self.active_calls.items()):
                    call_identity = active.identity
                    if call_identity.run_id != event.run_id:
                        continue
                    self.emitter.emit(
                        Packet(
                            identity=call_identity, obj=OperationStatus(status=status)
                        )
                    )
                    self.emitter.emit(Packet(identity=call_identity, obj=SectionEnd()))
                    del self.active_calls[key]
            self.emitter.emit(
                Packet(identity=identity, obj=OperationStatus(status=status))
            )
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
