"""Project feature output into response records and streaming packets."""

import threading
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from functools import partial

from pydantic import BaseModel

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
from onyx.agents.runtime import Agent, RunSnapshot
from onyx.agents.transcript import RunStatus
from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatResponseOutcome,
    ChatResponseSnapshot,
    ChatStepOutput,
    MessagePresentation,
    PresentationMode,
)
from onyx.chat.renderer import PacketRenderer, RenderConfig, render_message
from onyx.chat.tool_progress import project_tool_progress
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.configs.chat_configs import CHAT_RESPONSE_WAIT_TIMEOUT_S
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

_ARGUMENT_TOOLS = frozenset({BashTool.NAME, PythonTool.NAME})


class ResponseBinding:
    """Expose an application's response projection from its bound agent."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._result: Future[ChatResponseOutcome] = Future()
        self._agent: Agent | None = None
        self._project_response: Callable[[RunSnapshot], ChatResponseSnapshot] | None = (
            None
        )

    def bind_agent(
        self,
        agent: Agent,
        project_response: Callable[[RunSnapshot], ChatResponseSnapshot],
    ) -> None:
        with self._lock:
            self._agent = agent
            self._project_response = project_response

    def finish(self, outcome: ChatResponseOutcome) -> None:
        """Publish completion after the coordinator resolves persistence."""
        self._result.set_result(outcome)

    def fail(self, error: Exception) -> None:
        """Release waiters if the coordinator cannot build a terminal response."""
        if not self._result.done():
            self._result.set_exception(error)

    def result(self) -> ChatResponseOutcome:
        """Wait for application completion independently of stream delivery."""
        return self._result.result(timeout=CHAT_RESPONSE_WAIT_TIMEOUT_S)

    def snapshot(self, *, cancelled: bool = False) -> ChatResponseSnapshot:
        with self._lock:
            agent = self._agent
            project = self._project_response
        snapshot = agent.snapshot(cancelled=cancelled) if agent else None
        if snapshot is not None and project is not None:
            return project(snapshot)
        return ChatResponseSnapshot(
            answer=None,
            reasoning=None,
            request_params=None,
            citation_to_doc={},
            tool_calls=[],
            is_clarification=False,
            all_search_docs={},
            pre_answer_processing_time=None,
            transcript=None,
            cancelled=cancelled,
        )


def _render_config(
    metadata: BaseModel | None, *, parent_tool_name: str | None = None
) -> RenderConfig:
    config = RenderConfig(
        argument_tools=set(_ARGUMENT_TOOLS),
        mode=PresentationMode.CODING_THINKING
        if parent_tool_name == CODING_AGENT_TOOL_NAME
        else PresentationMode.ANSWER,
    )
    if isinstance(metadata, ChatStepOutput):
        config.citations = DynamicCitationProcessor(
            citation_mode=CitationMode.HYPERLINK
            if metadata.include_citations
            else CitationMode.REMOVE
        )
        config.citations.update_citation_mapping(metadata.sources)
        config.documents = metadata.documents or None
        config.pre_answer_seconds = metadata.elapsed_seconds
    elif isinstance(metadata, ResearchStepOutput):
        config.pre_answer_seconds = metadata.elapsed_seconds
        if metadata.phase == ResearchPhase.PLANNING:
            config.mode = PresentationMode.PLAN
        elif metadata.phase == ResearchPhase.RESEARCH:
            config.text_as_thinking = True
            config.think_tool = (
                THINK_TOOL_NAME if not metadata.is_reasoning_model else None
            )
        elif metadata.phase == ResearchPhase.REPORT:
            config.mode = (
                PresentationMode.REPORT
                if metadata.is_intermediate
                else PresentationMode.ANSWER
            )
            config.citations = DynamicCitationProcessor(
                citation_mode=CitationMode.KEEP_MARKERS
                if metadata.is_intermediate
                else CitationMode.HYPERLINK
            )
            config.citations.update_citation_mapping(metadata.sources)
            config.documents = list(metadata.sources.values()) or None
    return config


def project_response(
    snapshot: RunSnapshot,
    *,
    response_id: int,
    tool_ids: Mapping[str, int],
    initial_citations: CitationMapping | None = None,
) -> ChatResponseSnapshot:
    artifacts = project_tool_artifacts(snapshot, tool_ids, initial_citations)
    transcript = snapshot.transcript()
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
        transcript=transcript,
        cancelled=snapshot.status == RunStatus.CANCELLED,
        delivery_failed=snapshot.delivery_failed,
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
            config = _render_config(message.metadata, parent_tool_name=parent_tool_name)
            presentation.append(
                MessagePresentation(
                    run_id=node.run_id,
                    step_index=operation.step_index,
                    mode=config.mode,
                    text_as_thinking=config.text_as_thinking,
                    think_tool=config.think_tool,
                    argument_tools=config.argument_tools,
                    citation_mode=config.citations.citation_mode
                    if config.citations
                    else None,
                    citation_documents={
                        number: doc.document_id
                        for number, doc in config.citations.citation_to_doc.items()
                    }
                    if config.citations
                    else {},
                    document_ids=[doc.document_id for doc in config.documents or []],
                    pre_answer_seconds=config.pre_answer_seconds,
                )
            )
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
            metadata = message.metadata
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
                    "is_clarification": isinstance(metadata, ResearchStepOutput)
                    and metadata.phase == ResearchPhase.CLARIFICATION
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
            for child in node.children
        )
    return response.model_copy(update={"presentation": presentation})


def attach_response(
    agent: Agent,
    state: ResponseBinding,
    emitter: Emitter | None,
    *,
    response_id: int,
    tool_ids: Mapping[str, int],
    initial_citations: CitationMapping | None = None,
) -> None:
    state.bind_agent(
        agent,
        partial(
            project_response,
            response_id=response_id,
            tool_ids=dict(tool_ids),
            initial_citations=initial_citations,
        ),
    )
    if emitter is not None:
        agent.subscribe(ResponsePresenter(emitter).consume)


class ResponsePresenter:
    """Deliver one response tree's output through an application stream."""

    def __init__(self, emitter: Emitter) -> None:
        self.emitter = emitter
        self.renderers: dict[str, PacketRenderer] = {}
        self.active_calls: dict[tuple[str, str], PacketIdentity] = {}
        self.call_names: dict[tuple[str, str], str] = {}

    def _identity(self, event: AgentEvent, step_index: int) -> PacketIdentity:
        return PacketIdentity(
            response_id=self.emitter.response_id,
            run_id=event.run_id,
            message_id=f"{event.run_id}:{step_index}",
            parent_run_id=event.parent_run_id,
            parent_message_id=event.parent_message_id,
            parent_tool_call_id=event.parent_tool_call_id,
        )

    def consume(self, event: AgentEvent) -> None:
        if isinstance(event, MessageStartEvent):
            config = _render_config(
                event.metadata,
                parent_tool_name=self.call_names.get(
                    (event.parent_message_id or "", event.parent_tool_call_id or "")
                ),
            )
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
                self.active_calls[key] = identity
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
                packet = project_tool_progress(event.progress)
                if packet is not None:
                    self.emitter.emit(Packet(identity=identity, obj=packet))
            else:
                self.active_calls.pop(key)
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
                for key, call_identity in list(self.active_calls.items()):
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
