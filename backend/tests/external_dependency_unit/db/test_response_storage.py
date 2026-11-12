"""Response storage preserves accepted content, branch lineage, and compaction."""

import threading
from collections.abc import Generator
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from queue import Queue
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, event, func, inspect, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.unitofwork import UOWTransaction

from ee.onyx.db.usage_export import get_empty_chat_messages_entries__paginated
from ee.onyx.server.reporting.usage_export_models import FlowType
from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.compaction import working_messages
from onyx.agents.events import (
    MessageEndEvent,
    MessageStartEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.models import (
    AgentInfo,
    AgentMessageRequest,
    AgentState,
    CompactionCheckpoint,
    ExecutionCheckpoint,
    ExecutionStatus,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunAction,
    RunFailure,
    RunFailureKind,
    RunProgress,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
    messages_from_steps,
)
from onyx.agents.runtime import Run
from onyx.agents.tools import InputMode, PendingToolInput, ToolProgress
from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_utils import capture_chat_history, convert_chat_history
from onyx.chat.checkpoint import deserialize_checkpoint, serialize_checkpoint
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.citation_utils import message_citation_sources
from onyx.chat.emitter import Emitter
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.models import (
    ChatBranch,
    ChatMessageMetadata,
    ChatResponseSnapshot,
    CheckpointBinding,
    MessageRendering,
    ResponseCheckpoint,
    ResponseRecord,
)
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.chat.response import response_record, response_snapshot
from onyx.chat.run_store import ChatRunStore
from onyx.chat.tool_results import tool_result_sources
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SavedSearchDoc, SearchDoc, SearchDocsResponse
from onyx.db import chat_subagents
from onyx.db.chat import (
    MAX_AGENT_DEPTH,
    checkpoint_from_summary,
    delete_chat_session,
    delete_messages_and_files_from_chat_session,
    find_summary_for_ancestry,
    get_chat_message,
    get_chat_messages_by_session,
    get_or_create_root_message,
    load_message_branch,
    reserve_chat_response_ids,
    root_response_id,
    translate_db_message_to_chat_message_detail,
    visible_message_ids,
)
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    publish_checkpoint__no_commit,
)
from onyx.db.chat_inputs import (
    MAX_PENDING_MESSAGE_BYTES,
    agent_result_states,
    can_start_input,
    consume_inputs__no_commit,
    enqueue_message,
    fail_inbox_start__no_commit,
    has_pending_sends,
    latest_agent_response,
    lock_agent,
    pending_inputs,
    read_run_inputs,
)
from onyx.db.chat_response import (
    read_chat_execution,
    read_response__no_commit,
    read_response_replay_data,
    read_response_status__no_commit,
    read_response_steps,
    reserve_child_response__no_commit,
    save_chat_response_to_db,
    save_chat_turn,
    save_response_content,
    save_response_record__no_commit,
    write_response_items,
)
from onyx.db.chat_subagents import (
    _load_history,
    load_session_agent_metadata,
    lookup_session_agent,
    read_agent_completions,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import (
    ChatInput,
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatResponseCheckpoint,
    ChatResponseItem,
    ChatSession,
    Tool,
    User,
)
from onyx.db.models import SearchDoc as StoredSearchDoc
from onyx.db.models import ToolCall as StoredToolCall
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchMessageMetadata,
    ResearchPhase,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    ImageContentPart,
    ImageUrlDetail,
    Message,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.session_loading import (
    load_session_tools,
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    CitationInfo,
    CodingAgentFinal,
    ImageGenerationFinal,
    MemoryToolDelta,
    Packet,
    PythonToolDelta,
    SearchToolDocumentsDelta,
    SearchToolQueriesDelta,
)
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    FileReadResult,
    GeneratedImage,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryOperation,
    MemoryUpdated,
    PythonExecutionDelta,
    PythonExecutionFile,
    ToolCallInfo,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.subagents.models import ChatConfiguration
from onyx.utils.threadpool_concurrency import start_thread_future
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


def _steps(
    run_id: str,
    messages: list[Message],
    status: ExecutionStatus = ExecutionStatus.COMPLETE,
) -> list[StepRecord]:
    steps: list[StepRecord] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            message.id = message.id or f"{run_id}:{len(steps)}"
            steps.append(StepRecord(message=message, generation_status=status))
        else:
            assert isinstance(message, ToolResultMessage)
            steps[-1].tools[message.tool_call_id] = ToolExecutionRecord(
                status=ExecutionStatus.ERROR
                if message.is_error
                else ExecutionStatus.COMPLETE,
                result=message,
            )
    return steps


@pytest.fixture
def tool_record(db_session: Session) -> Generator[Tool, None, None]:
    tool = Tool(name="response test", in_code_tool_id=f"response-test-{uuid4()}")
    db_session.add(tool)
    db_session.flush()
    tool_id = tool.id
    yield tool
    db_session.rollback()
    db_session.execute(delete(Tool).where(Tool.id == tool_id))
    db_session.commit()


@pytest.fixture
def conversation(db_session: Session) -> Generator[ChatSession, None, None]:
    session = ChatSession(id=uuid4(), description="response storage test")
    db_session.add(session)
    db_session.flush()
    session_id = session.id
    document_ids: set[int] = set()

    def track_documents(session: Session, _context: UOWTransaction) -> None:
        document_ids.update(
            row.id for row in session.new if isinstance(row, StoredSearchDoc)
        )

    event.listen(db_session, "after_flush", track_documents)
    try:
        yield session
    finally:
        event.remove(db_session, "after_flush", track_documents)
        db_session.rollback()
        document_ids.update(
            db_session.scalars(
                select(ChatMessage__SearchDoc.search_doc_id)
                .join(
                    ChatMessage,
                    ChatMessage.id == ChatMessage__SearchDoc.chat_message_id,
                )
                .where(ChatMessage.chat_session_id == session_id)
            )
        )
        db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        if document_ids:
            db_session.execute(
                delete(StoredSearchDoc).where(StoredSearchDoc.id.in_(document_ids))
            )
        db_session.commit()


@pytest.fixture
def executed_sql(db_session: Session) -> Generator[list[str], None, None]:
    statements: list[str] = []

    def capture_statement(statement: str, **_event: object) -> None:
        # SQLAlchemy supplies the unused connection, cursor, and execution parameters.
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement, named=True)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)


def _response(
    db_session: Session,
    conversation: ChatSession,
    text: str = "Question",
    previous: ChatMessage | None = None,
    question: ChatMessage | None = None,
) -> ChatMessage:
    selects_response = question is None
    if question is None:
        question = ChatMessage(
            chat_session_id=conversation.id,
            parent_message_id=previous.id if previous else None,
            message=text,
            token_count=len(text),
            message_type=MessageType.USER,
        )
        db_session.add(question)
        db_session.flush()
        if previous is not None:
            previous.latest_child_message_id = question.id
    response = ChatMessage(
        chat_session_id=conversation.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    if selects_response:
        # A new turn's response is the selected one, as when a turn reserves it.
        question.latest_child_message_id = response.id
        db_session.flush()
    return response


def _record(response: ChatMessage, answer: str = "Answer") -> ResponseRecord:
    assert response.parent_message is not None
    run_id = str(response.id)
    return ResponseRecord(
        agent_id=str(response.chat_session_id),
        run_id=run_id,
        status=RunStatus.COMPLETE,
        input_messages=[
            UserMessage(
                id=f"chat:{response.parent_message.id}",
                content=response.parent_message.message,
            )
        ],
        steps=_steps(run_id, [AssistantMessage(content=[TextContent(text=answer)])]),
        answer_step_index=0,
    )


def _save(db_session: Session, response: ChatMessage, record: ResponseRecord) -> None:
    save_response_content(response, record, db_session=db_session, persist_content=True)
    db_session.flush()
    db_session.expire(response)


def _child_record(
    db_session: Session,
    parent: ResponseRecord,
    child_id: UUID,
    answer: str,
    previous: str | None = None,
    *,
    path: str | None = None,
    tool_name: str = "delegate",
) -> ResponseRecord:
    path = path or f"{parent.agent_path}/research"
    parent.steps = _steps(
        parent.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name=tool_name, arguments={})]
            )
        ],
    )

    parent_row = db_session.get(ChatMessage, int(parent.run_id))
    assert parent_row is not None
    root_id = root_response_id(db_session, parent_row)
    save_response_record__no_commit(db_session, root_id, parent)
    instruction = UserMessage(content=f"Find {answer}")
    run_id = str(
        reserve_child_response__no_commit(
            db_session,
            root_id,
            agent=AgentInfo(
                id=str(child_id),
                path=path,
                parent_id=parent.agent_id,
                description="Research child",
                restoration_config=None,
            ),
            instruction=instruction,
            previous_response_id=int(previous) if previous else None,
            parent_response_id=int(parent.run_id),
            parent_message_id=f"{parent.run_id}:0",
            parent_tool_call_id="delegate",
            delivers_result=tool_name in ("spawn_agent", "send_message"),
        )
    )
    child = ResponseRecord(
        agent_id=str(child_id),
        agent_path=path,
        run_id=run_id,
        previous_run_id=previous,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
        status=RunStatus.COMPLETE,
        input_messages=[
            UserMessage(id=f"run:{run_id}:input:0", content=f"Find {answer}")
        ],
        steps=_steps(run_id, [AssistantMessage(content=[TextContent(text=answer)])]),
        answer_step_index=0,
    )
    parent.child_runs.append(child)
    return child


def _result_input(run_id: str) -> UserMessage:
    return UserMessage(
        id=f"agent-result:{run_id}",
        content="Result",
        metadata=InputMessageMetadata(
            source=InputSource.AGENT_RESULT, source_run_id=run_id
        ),
    )


@pytest.mark.parametrize("background", [False, True])
def test_agent_results_are_scoped_to_spawner_and_root_branch(
    db_session: Session, conversation: ChatSession, background: bool
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(
        db_session,
        parent,
        uuid4(),
        "Child report",
        tool_name="spawn_agent" if background else "research_agent",
    )
    grandchild = _child_record(
        db_session, child, uuid4(), "Grandchild report", tool_name="spawn_agent"
    )
    _save(db_session, response, parent)
    branch = [response.id]

    def unread(visible: list[int], recipient: UUID) -> dict[int, RunStatus]:
        return {
            result.response_id: result.status
            for result in agent_result_states(db_session, visible, recipient)
        }

    assert unread(branch, conversation.id) == (
        {int(child.run_id): RunStatus.COMPLETE} if background else {}
    )
    assert unread(branch, UUID(child.agent_id or "")) == {
        int(grandchild.run_id): RunStatus.COMPLETE
    }
    # A sibling root branch neither lists nor consumes the result.
    sibling = _response(db_session, conversation)
    _save(db_session, sibling, _record(sibling))
    assert unread([sibling.id], conversation.id) == {}
    assert unread([sibling.id], UUID(child.agent_id or "")) == {}
    if not background:
        return
    sibling.response_status = RunStatus.RUNNING
    assert not consume_inputs__no_commit(
        db_session,
        sibling.id,
        [_result_input(child.run_id)],
        [sibling.id],
        ownership_version=None,
    )
    assert consume_inputs__no_commit(
        db_session,
        sibling.id,
        [_result_input(child.run_id)],
        branch,
        ownership_version=None,
    )
    assert unread(branch, conversation.id) == {}


def test_later_child_run_keeps_earlier_unread_result(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(
        db_session, parent, uuid4(), "First assignment", tool_name="spawn_agent"
    )
    grandchild = _child_record(
        db_session, child, uuid4(), "Evidence", tool_name="spawn_agent"
    )
    _save(db_session, response, parent)
    assert child.agent_id is not None
    later_response = _response(db_session, conversation, previous=response)
    later_parent = _record(later_response)
    another_assignment = _child_record(
        db_session,
        later_parent,
        UUID(child.agent_id),
        "Second assignment",
        child.run_id,
        tool_name="send_message",
    )
    _save(db_session, later_response, later_parent)
    branch = [response.id, later_response.id]
    expected = {
        int(child.run_id): RunStatus.COMPLETE,
        int(another_assignment.run_id): RunStatus.COMPLETE,
    }
    assert {
        result.response_id: result.status
        for result in agent_result_states(db_session, branch, conversation.id)
    } == expected
    later_response.response_status = RunStatus.RUNNING
    assert consume_inputs__no_commit(
        db_session,
        later_response.id,
        [_result_input(run_id) for run_id in (child.run_id, another_assignment.run_id)],
        branch,
        ownership_version=None,
    )
    assert agent_result_states(db_session, branch, conversation.id) == []

    # A running follow-up whose owner is gone is saved as interrupted.
    orphan_id = reserve_child_response__no_commit(
        db_session,
        response.id,
        agent=AgentInfo(
            id=grandchild.agent_id or "",
            path=grandchild.agent_path,
            parent_id=child.agent_id,
            description="",
            restoration_config=None,
        ),
        instruction=None,
        previous_response_id=int(grandchild.run_id),
        parent_response_id=int(child.run_id),
        parent_message_id=f"{child.run_id}:0",
        parent_tool_call_id="delegate",
        delivers_result=True,
    )
    orphan = db_session.get(ChatMessage, orphan_id)
    assert orphan is not None and orphan.parent_message is not None
    assert orphan.parent_message.message_type == MessageType.AGENT_RESULTS
    orphan.response_status = RunStatus.RUNNING
    db_session.commit()
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    owner = ChatRunStore(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=conversation.id,
        response_id=later_response.id,
        visible_response_ids=branch,
        cache=cache,
        follow_up_steps=4,
        control_cache=cache,
    )
    coordinator = AgentCoordinator()
    owner.bind(
        coordinator,
        build_agent=lambda _: pytest.fail("No execution should be restored"),
    )
    try:
        owner.poll_control()
        db_session.refresh(orphan)
        assert orphan.response_status == RunStatus.ERROR
        assert orphan.response_failure is not None
        assert orphan.response_failure.kind == RunFailureKind.EXECUTION
    finally:
        assert coordinator.close(timeout=10)


def test_agent_result_is_accepted_once_by_concurrent_consumers(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(
        db_session, parent, uuid4(), "Report", tool_name="spawn_agent"
    )
    _save(db_session, response, parent)
    response.response_status = RunStatus.RUNNING
    db_session.commit()
    response_id = response.id
    barrier = threading.Barrier(2)

    def consume() -> bool:
        with Session(db_session.get_bind()) as session:
            barrier.wait(10)
            accepted = consume_inputs__no_commit(
                session,
                response_id,
                [_result_input(child.run_id)],
                [response_id],
                ownership_version=None,
            )
            session.commit()
            return accepted

    workers = [
        start_thread_future(consume, name=f"test-consume-{index}") for index in range(2)
    ]
    assert sorted(worker.result(timeout=20) for worker in workers) == [False, True]


def test_abandoned_background_child_is_delivered_as_failure(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(
        db_session, parent, uuid4(), "Partial output", tool_name="spawn_agent"
    )
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None
    child_row.response_status = RunStatus.RUNNING
    db_session.commit()
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    run_store = ChatRunStore(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=conversation.id,
        response_id=response.id,
        visible_response_ids=[response.id],
        cache=cache,
        follow_up_steps=4,
        control_cache=cache,
    )
    coordinator = AgentCoordinator()
    run_store.bind(
        coordinator, build_agent=lambda _: pytest.fail("No execution is restored")
    )

    # A control poll saves the lost child as failed; the root's next step receives it.
    try:
        run_store.poll_control()
    finally:
        assert coordinator.close(timeout=10)
    [received] = run_store.receive_inputs(
        Run.from_snapshot(
            RunState(
                run_id=str(response.id),
                agent_id=str(conversation.id),
                status=RunStatus.COMPLETE,
            )
        )
    )
    assert isinstance(received.metadata, InputMessageMetadata)
    assert received.metadata.source_run_id == child.run_id
    assert '"status": "error"' in received.text
    db_session.expire_all()
    stored = db_session.get(ChatMessage, int(child.run_id))
    assert stored is not None and stored.response_status == RunStatus.ERROR
    assert stored.response_failure is not None
    assert stored.response_failure.kind == RunFailureKind.EXECUTION


def test_agent_completion_preserves_cited_output_and_durable_input_receipt(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(
        db_session, parent, uuid4(), "Child source [2].", tool_name="spawn_agent"
    )
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None
    snapshot = response_snapshot(child)
    snapshot.steps[0].message.metadata = ChatMessageMetadata(
        sources={2: _source_doc("child-source")}
    )
    projected = project_response(snapshot, tool_ids={})
    save_chat_turn(
        message_text=projected.answer or "",
        reasoning_tokens=projected.reasoning,
        tool_calls=projected.tool_calls,
        citation_to_doc=projected.citation_to_doc,
        all_search_docs=projected.all_search_docs,
        db_session=db_session,
        assistant_message=child_row,
        response_record=projected.response,
        presentation=projected.presentation,
    )
    db_session.expire_all()
    answer = db_session.scalar(
        select(ChatResponseItem).where(ChatResponseItem.chat_message_id == child_row.id)
    )
    assert answer is not None
    db_session.expire(answer, ["inputs"])
    [completion] = read_agent_completions(db_session, [child_row.id])
    assert "inputs" in inspect(answer).unloaded
    assert completion.run_id == child.run_id
    assert completion.agent_path == "/root/research"
    assert completion.output is not None
    assert completion.output.text == "Child source [2]."
    assert message_citation_sources(completion.output)[2].document_id == "child-source"

    # A receipt is retained with the generation that consumed the result.
    follow_up = _response(db_session, conversation, previous=response)
    record = _record(follow_up, "Parent source [5].")
    record.steps[0].input_messages = [
        UserMessage(id=completion.message_id, content="Child source [5].")
    ]
    restored = response_snapshot(record)
    restored.steps[0].message.metadata = ChatMessageMetadata(
        sources={5: _source_doc("child-source")}
    )
    projected = project_response(restored, tool_ids={})
    save_chat_turn(
        message_text=projected.answer or "",
        reasoning_tokens=projected.reasoning,
        tool_calls=projected.tool_calls,
        citation_to_doc=projected.citation_to_doc,
        all_search_docs=projected.all_search_docs,
        db_session=db_session,
        assistant_message=follow_up,
        response_record=projected.response,
        presentation=projected.presentation,
    )
    db_session.expire_all()
    [history] = capture_chat_history([follow_up], {}, len)
    incoming, answer = history.response_messages
    assert incoming.id == completion.message_id
    assert incoming.text == "Child source [5]."
    assert message_citation_sources(answer)[5].document_id == "child-source"


@pytest.mark.parametrize("citation_only", [False, True])
def test_metadata_sources_survive_storage_without_search_results(
    db_session: Session,
    conversation: ChatSession,
    tool_record: Tool,
    citation_only: bool,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    child_id = uuid4()
    _child_record(db_session, record, child_id, "Child source [2].")
    record.steps.append(
        StepRecord(
            message=AssistantMessage(
                id=f"{record.run_id}:1", content=[TextContent(text="Root source [1].")]
            ),
            generation_status=ExecutionStatus.COMPLETE,
        )
    )
    record.answer_step_index = 1
    snapshot = response_snapshot(record)
    documents = [
        SearchDoc(
            document_id=name,
            chunk_ind=0,
            semantic_identifier=name,
            link=f"https://example.com/{name}",
            blurb=name,
            source_type=DocumentSource.GOOGLE_DRIVE,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for name in ("root-source", "child-source", "display-source")
    ]
    snapshot.steps[1].message.metadata = ChatMessageMetadata(
        sources={1: documents[0]}, documents=[documents[2]]
    )
    snapshot.child_runs[0].steps[0].message.metadata = ResearchMessageMetadata(
        phase=ResearchPhase.REPORT,
        is_reasoning_model=False,
        sources={2: documents[1]},
    )
    projected = project_response(
        snapshot,
        tool_ids={"delegate": tool_record.id},
        registrations=[
            AgentInfo(
                id=str(child_id),
                path="/root/research",
                parent_id=str(conversation.id),
                description="Research child",
                restoration_config=None,
            )
        ],
    )
    assert set(projected.all_search_docs) == {doc.document_id for doc in documents}
    assert projected.citation_to_doc == {1: documents[0]}
    emitted_citations = {
        citation.citation_number for citation in projected.citation_info
    }
    if citation_only:
        projected.all_search_docs.pop(documents[1].document_id)
        projected.citation_to_doc[2] = documents[1]
        emitted_citations.add(2)
    save_chat_turn(
        message_text=projected.answer or "",
        reasoning_tokens=projected.reasoning,
        tool_calls=projected.tool_calls,
        citation_to_doc=projected.citation_to_doc,
        all_search_docs=projected.all_search_docs,
        db_session=db_session,
        assistant_message=response,
        emitted_citations=emitted_citations,
        response_record=projected.response,
        presentation=projected.presentation,
    )
    db_session.expire_all()
    assert {doc.document_id for doc in response.search_docs} == {
        doc.document_id for doc in documents
    }
    assert response.citations and set(response.citations) == (
        {"1", "2"} if citation_only else {"1"}
    )
    replay = translate_assistant_message_to_packets(
        response, load_session_tools([response], db_session), db_session
    )
    assert {
        packet.obj.document_id
        for packet in replay
        if isinstance(packet.obj, CitationInfo)
    } == {"root-source", "child-source"}
    child = db_session.get(ChatSession, child_id)
    assert child is not None
    restored = _load_history(
        db_session,
        ChatBranch(
            chat_session_id=conversation.id,
            message_ids=visible_message_ids(db_session, response),
        ),
        child,
    )
    assert restored.sources[2].document_id == "child-source"
    response.search_docs = [
        doc for doc in response.search_docs if doc.document_id != "child-source"
    ]
    db_session.flush()
    with pytest.raises(ValueError, match="Cited source is unavailable"):
        _load_history(
            db_session,
            ChatBranch(
                chat_session_id=conversation.id,
                message_ids=visible_message_ids(db_session, response),
            ),
            child,
        )


def _source_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier=document_id,
        link=f"https://example.com/{document_id}",
        blurb=document_id,
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )


@pytest.mark.parametrize(
    ("tool_name", "details"),
    [
        (
            SearchTool.NAME,
            SearchDocsResponse(
                queries=["query"],
                search_docs=[_source_doc("alpha"), _source_doc("beta")],
                displayed_docs=[_source_doc("beta")],
                citation_mapping={1: "alpha", 2: "beta"},
            ),
        ),
        (
            "research_agent",
            ResearchAgentCallResult(
                intermediate_report="Report",
                citation_mapping={3: _source_doc("gamma")},
            ),
        ),
    ],
)
def test_tool_result_sources_survive_save_and_reload(
    db_session: Session,
    conversation: ChatSession,
    tool_record: Tool,
    tool_name: str,
    details: BaseModel,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="call", name=tool_name, arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="call",
                tool_name=tool_name,
                content="Found",
                details=details,
            ),
            AssistantMessage(content=[TextContent(text="Answer")]),
        ],
    )
    record.answer_step_index = 1
    live = tool_result_sources(details)
    assert live is not None and live.citations
    projected = project_response(
        response_snapshot(record), tool_ids={tool_name: tool_record.id}
    )
    save_chat_turn(
        message_text=projected.answer or "",
        reasoning_tokens=projected.reasoning,
        tool_calls=projected.tool_calls,
        citation_to_doc=projected.citation_to_doc,
        all_search_docs=projected.all_search_docs,
        db_session=db_session,
        assistant_message=response,
        emitted_citations=set(),
        response_record=projected.response,
        presentation=projected.presentation,
    )
    db_session.expire_all()

    history = capture_chat_history([response], {}, len)
    [restored] = [
        message
        for message in history[0].response_messages
        if isinstance(message, ToolResultMessage)
    ]
    sources = tool_result_sources(restored.details)
    assert sources is not None
    assert {number: doc.document_id for number, doc in sources.citations.items()} == {
        number: doc.document_id for number, doc in live.citations.items()
    }
    assert [doc.document_id for doc in sources.documents] == [
        doc.document_id for doc in live.documents
    ]
    assert {
        number: doc.document_id
        for number, doc in message_citation_sources(restored).items()
    } == {number: doc.document_id for number, doc in live.citations.items()}
    tool = db_session.scalar(
        select(StoredToolCall).where(
            StoredToolCall.parent_chat_message_id == response.id
        )
    )
    assert tool is not None
    assert [doc.document_id for doc in tool.search_docs] == [
        doc.document_id for doc in live.displayed or []
    ]


def test_thinking_preserves_signed_content_and_final_display_text(
    db_session: Session, conversation: ChatSession, tool_record: Tool
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    pre_tool = ThinkingContent(
        text="Before tools",
        blocks=[ThinkingBlock(thinking="Before tools", signature="tool-signature")],
    )
    final = ThinkingContent(
        text="Before answer",
        blocks=[ThinkingBlock(thinking="Before answer", signature="answer-signature")],
    )
    calls = [
        ToolCall(id=name, name="lookup", arguments={}) for name in ("first", "second")
    ]
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(content=[pre_tool, *calls]),
            *[
                ToolResultMessage(
                    tool_call_id=call.id, tool_name=call.name, content="Result"
                )
                for call in calls
            ],
            AssistantMessage(content=[final, TextContent(text="Raw answer")]),
        ],
    )
    record.answer_step_index = 1
    save_chat_turn(
        message_text="Formatted answer",
        reasoning_tokens=final.text,
        tool_calls=[
            ToolCallInfo(
                message_id=f"{record.run_id}:0",
                parent_tool_call_id=None,
                turn_index=0,
                tab_index=index,
                tool_name=call.name,
                tool_call_id=call.id,
                tool_id=tool_record.id,
                reasoning_tokens=pre_tool.text,
                tool_call_arguments={},
                tool_call_response="Result",
            )
            for index, call in enumerate(calls)
        ],
        citation_to_doc={},
        all_search_docs={},
        db_session=db_session,
        assistant_message=response,
        response_record=record,
    )
    db_session.expire_all()

    assert response.message == "Formatted answer"
    assert response.reasoning_tokens == final.text
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 2
    steps = read_response_steps(response)
    assert steps[0].message.content[0] == pre_tool
    assert steps[1].message.content == [final, TextContent(text="Raw answer")]


@pytest.mark.parametrize(
    "details",
    [
        None,
        LlmPythonExecutionResult(
            stdout="hello", stderr="", exit_code=0, timed_out=False, generated_files=[]
        ),
        LlmBashExecutionResult(stdout="hello", stderr="", exit_code=0, timed_out=False),
        MemoryUpdated(
            memory_text="Prefers tea", operation=MemoryOperation.ADD, memory_id=12
        ),
        FileReadResult(
            file_name="notes.txt",
            file_id="notes",
            start_char=0,
            end_char=5,
            total_chars=5,
        ),
        CodingAgentCallResult(answer="Done"),
        ResearchAgentCallResult(intermediate_report="Report", citation_mapping={}),
        FinalImageGenerationResponse(
            generated_images=[
                GeneratedImage(
                    file_id="image", url="/api/chat/file/image", revised_prompt="Tree"
                )
            ]
        ),
        CustomToolCallSummary(
            tool_name="custom",
            response_type="csv",
            tool_result=CustomToolUserFileSnapshot(file_ids=["csv-file"]),
        ),
        CustomToolCallSummary(
            tool_name="custom",
            response_type="json",
            tool_result={"file_ids": ["not-a-file-reference"], "other": 1},
        ),
        ToolExecutionError(message="Tool failed"),
        SearchDocsResponse(
            queries=["query"], search_docs=[], citation_mapping={}, displayed_docs=[]
        ),
    ],
)
def test_tool_result_details_round_trip_without_legacy_output(
    db_session: Session, conversation: ChatSession, details: BaseModel | None
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    result = ToolResultMessage(
        tool_call_id="call",
        tool_name="lookup",
        content="Model output",
        details=details,
        is_error=isinstance(details, ToolExecutionError),
    )
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="call", name="lookup", arguments={})]
            ),
            result,
            AssistantMessage(content=[TextContent(text="Answer")]),
        ],
    )
    record.answer_step_index = 1
    _save(db_session, response, record)
    db_session.expire_all()

    restored = read_response_steps(response)[0].tools["call"].result
    assert restored is not None
    assert restored.content == result.content
    assert restored.is_error == result.is_error
    assert type(restored.details) is type(details)
    assert restored.details == details
    tool = db_session.scalar(
        select(StoredToolCall).where(
            StoredToolCall.parent_chat_message_id == response.id
        )
    )
    assert tool is not None
    assert tool.legacy_response == ""
    assert tool.tool_call_response == result.content
    assert tool.generated_images is None


def test_suspended_search_result_restores_after_database_round_trip(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation, text="Search then ask")
    assert response.parent_message is not None
    instruction = UserMessage(
        id=f"chat:{response.parent_message.id}", content=response.parent_message.message
    )
    snapshot = RunState(
        run_id=str(response.id),
        agent_id=str(conversation.id),
        status=RunStatus.SUSPENDED,
        input_messages=[instruction],
        steps=[
            StepRecord(
                input_messages=[
                    UserMessage(
                        id="follow-up-instruction",
                        content="Include the supporting evidence.",
                        metadata=InputMessageMetadata(source=InputSource.HUMAN),
                    )
                ],
                message=AssistantMessage(
                    id="generation",
                    content=[
                        ToolCall(id="search", name="search", arguments={}),
                        ToolCall(id="ask", name="ask", arguments={}),
                    ],
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "search": ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            content="Found",
                            tool_call_id="search",
                            tool_name="search",
                            details=SearchDocsResponse(
                                queries=["query"],
                                search_docs=[],
                                citation_mapping={},
                                displayed_docs=[],
                            ),
                        ),
                    )
                },
            )
        ],
        progress=RunProgress(
            tool_configuration_digest="test-tool-configuration",
            step_limit=3,
            action=RunAction.TOOLS,
            options=GenerationOptions(),
            previous_options=GenerationOptions(),
            finalized_tool_call_ids={"search"},
            pending_tool_calls={
                "ask": PendingToolInput(
                    request_id="ask-user", prompt="Continue?", mode=InputMode.EXECUTE
                )
            },
        ),
    )
    context = AgentState(messages=[instruction])
    record = response_record(snapshot)
    binding = CheckpointBinding(tenant_id="public", response_id=str(response.id))
    checkpoint = serialize_checkpoint(
        ExecutionCheckpoint(agent_state=context, run_state=snapshot), record, binding
    )
    save_response_record__no_commit(db_session, response.id, record)
    db_session.flush()
    db_session.expire_all()
    saved = read_response__no_commit(db_session, int(snapshot.run_id))
    assert saved is not None
    restored = deserialize_checkpoint(checkpoint, saved.response, context, binding)
    assert restored.run_state.model_dump() == snapshot.model_dump()


def test_response_tools_flush_together_and_keep_result_identity(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    calls = [ToolCall(id=f"call-{i}", name="search", arguments={}) for i in range(4)]
    messages: list[Message] = [AssistantMessage(content=list(calls))]
    messages.extend(
        ToolResultMessage(
            id=f"result:{call.id}",
            tool_call_id=call.id,
            tool_name=call.name,
            content=call.id,
        )
        for call in calls
    )
    steps = _steps(str(uuid4()), messages)
    flushes = 0

    def count_flush(**_event: object) -> None:
        nonlocal flushes
        flushes += 1

    # Repeat the write to cover both new and existing tool relationships.
    for _ in range(2):
        flushes = 0
        event.listen(db_session, "before_flush", count_flush, named=True)
        try:
            tools = write_response_items(
                db_session,
                response,
                ResponseRecord(
                    run_id="tools",
                    status=RunStatus.COMPLETE,
                    steps=steps,
                ),
                {},
            )
        finally:
            event.remove(db_session, "before_flush", count_flush)
        assert flushes == 1
        assert len({tool.id for tool in tools.values()}) == len(calls)
        db_session.expire_all()
        assert [step.model_dump() for step in read_response_steps(response)] == [
            step.model_dump() for step in steps
        ]
        assert len(response.response_items) == 1
        assert {tool.result.id for tool in tools.values() if tool.result} == {
            f"result:{call.id}" for call in calls
        }


@pytest.mark.parametrize(
    "first_status", [ExecutionStatus.COMPLETE, ExecutionStatus.CANCELLED]
)
def test_resumed_tool_results_keep_row_identity_and_model_call_order(
    db_session: Session, conversation: ChatSession, first_status: ExecutionStatus
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.status = RunStatus.SUSPENDED
    record.answer_step_index = None
    step = StepRecord(
        message=AssistantMessage(
            id=f"{record.run_id}:0",
            content=[
                ToolCall(id="first", name="search", arguments={}),
                ToolCall(id="second", name="search", arguments={}),
            ],
        ),
        generation_status=ExecutionStatus.COMPLETE,
        tools={
            "first": ToolExecutionRecord(status=ExecutionStatus.RUNNING),
            "second": ToolExecutionRecord(
                status=ExecutionStatus.COMPLETE,
                result=ToolResultMessage(
                    id=f"{record.run_id}:0:result:second",
                    tool_call_id="second",
                    tool_name="search",
                    content="Second result",
                ),
            ),
        },
    )
    record.steps = [step]
    save_response_record__no_commit(db_session, response.id, record)
    db_session.flush()
    db_session.expire(response)
    assert response.tool_calls is not None
    second_tool = next(
        tool for tool in response.tool_calls if tool.tool_call_id == "second"
    )
    second_tool_id = second_tool.id
    assert len(response.response_items) == 1
    suspended = read_chat_execution(response)
    assert suspended is not None and suspended.response is not None
    assert [step.model_dump() for step in suspended.response.steps] == [
        step.model_dump() for step in record.steps
    ]
    assert suspended.response.steps[0].tools["first"].result is None

    step.tools["first"] = ToolExecutionRecord(
        status=first_status,
        result=ToolResultMessage(
            id=f"{record.run_id}:0:result:first",
            tool_call_id="first",
            tool_name="search",
            content="First result",
            is_error=first_status == ExecutionStatus.CANCELLED,
        ),
    )
    record.steps.append(
        StepRecord(
            message=AssistantMessage(
                id=f"{record.run_id}:1", content=[TextContent(text="Answer")]
            ),
            generation_status=ExecutionStatus.COMPLETE,
        )
    )
    record.status = RunStatus.COMPLETE
    record.answer_step_index = 1
    save_response_record__no_commit(db_session, response.id, record)
    db_session.flush()
    db_session.expire(response)
    restored = read_chat_execution(response)
    assert restored is not None and restored.response is not None
    assert [step.model_dump() for step in restored.response.steps] == [
        step.model_dump() for step in record.steps
    ]
    assert [message.text for message in restored.response.messages] == [
        "",
        "First result",
        "Second result",
        "Answer",
    ]
    assert response.tool_calls is not None
    stored_second = next(
        tool for tool in response.tool_calls if tool.tool_call_id == "second"
    )
    assert stored_second.id == second_tool_id
    assert stored_second.result is not None
    assert stored_second.result.id == f"{record.run_id}:0:result:second"
    assert restored.response.messages[1].id == f"{record.run_id}:0:result:first"
    assert len(response.response_items) == 2
    assert restored.response.answer_step_index == 1


def test_response_items_preserve_order_provider_metadata_and_tool_identity(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    messages: list[Message] = [
        AssistantMessage(
            content=[
                ThinkingContent(
                    text="Reasoning",
                    blocks=[ThinkingBlock(thinking="Reasoning", signature="signature")],
                ),
                TextContent(text="Checking sources."),
                ToolCall(id="same-id", name="search", arguments={"query": "first"}),
            ]
        ),
        ToolResultMessage(
            id=f"{record.run_id}:0:result:same-id",
            tool_call_id="same-id",
            tool_name="search",
            content="First result",
        ),
        AssistantMessage(
            content=[
                TextContent(text="Checking again."),
                ToolCall(id="same-id", name="search", arguments={"query": "second"}),
            ]
        ),
        ToolResultMessage(
            id=f"{record.run_id}:1:result:same-id",
            tool_call_id="same-id",
            tool_name="search",
            content="Second result",
        ),
        AssistantMessage(content=[TextContent(text="Final answer")]),
    ]
    answer_index = 2

    record.steps = _steps(record.run_id, messages, ExecutionStatus(record.status.value))
    record.steps[1].input_messages = [
        UserMessage(id="agent-result:child-one", content="First child completed")
    ]
    record.steps[2].input_messages = [
        UserMessage(id="agent-result:child-two", content="Second child completed")
    ]

    record.answer_step_index = answer_index
    _save(db_session, response, record)
    # Storage row order must not change generation or tool-result order.
    response.response_items.reverse()
    restored = (
        execution.response if (execution := read_chat_execution(response)) else None
    )
    assert restored is not None
    assert [message.text for message in restored.messages] == [
        message.text for message in record.messages
    ]
    first = restored.messages[0]
    assert isinstance(first, AssistantMessage)
    assert first.content[0] == record.messages[0].content[0]
    assert restored.answer_step_index == 2
    assert restored.messages[6].text == "Final answer"
    items = messages_from_steps(read_response_steps(response))
    assert items == restored.messages
    tools = list(
        db_session.scalars(
            select(StoredToolCall).where(
                StoredToolCall.parent_chat_message_id == response.id
            )
        )
    )
    assert len(tools) == 2
    assert {tool.result.text for tool in tools if tool.result} == {
        "First result",
        "Second result",
    }
    assert all(tool.legacy_response == "" for tool in tools)
    assert len(response.response_items) == 3
    assert [message.id for message in restored.messages] == [
        message.id for message in record.messages
    ]
    assert {tool.result.id for tool in tools if tool.result} == {
        f"{record.run_id}:0:result:same-id",
        f"{record.run_id}:1:result:same-id",
    }


@pytest.mark.parametrize(
    ("status", "generation_status"),
    [
        (RunStatus.ERROR, ExecutionStatus.ERROR),
        (RunStatus.CANCELLED, ExecutionStatus.CANCELLED),
        (RunStatus.LIMIT, ExecutionStatus.COMPLETE),
    ],
)
def test_empty_generation_retains_outcome_and_rendering(
    db_session: Session,
    conversation: ChatSession,
    status: RunStatus,
    generation_status: ExecutionStatus,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    messages: list[Message] = [
        AssistantMessage(
            id="empty-generation",
            content=[],
            error_message="Failed"
            if generation_status == ExecutionStatus.ERROR
            else None,
            stop_reason="error" if generation_status == ExecutionStatus.ERROR else None,
        )
    ]
    record.status = status
    record.steps = _steps(record.run_id, messages, generation_status)

    record.failure = (
        RunFailure(kind=RunFailureKind.EXECUTION, message="Failed")
        if status == RunStatus.ERROR
        else None
    )
    save_response_content(
        response,
        record,
        db_session=db_session,
        persist_content=True,
        presentation={"empty-generation": MessageRendering(text_as_thinking=True)},
    )
    db_session.expire(response)
    restored = (
        execution.response if (execution := read_chat_execution(response)) else None
    )
    assert restored is not None
    assert restored.status == status
    assert restored.failure == record.failure
    assert len(restored.messages) == 1
    restored_message = restored.messages[0]
    assert isinstance(restored_message, AssistantMessage)
    assert restored_message.stop_reason == record.steps[0].message.stop_reason
    assert restored.steps[0].generation_status == generation_status
    execution = read_chat_execution(response)
    assert execution is not None
    assert execution.presentation["empty-generation"].text_as_thinking
    saved_settings = response.response_items[0].rendering
    assert saved_settings is not None
    assert "run_id" not in saved_settings and "step_index" not in saved_settings


@pytest.mark.parametrize(
    ("raw_arguments", "arguments_complete", "argument_error"),
    [
        ('{"query": "half', False, None),
        ('{"query":}', True, "Invalid JSON arguments"),
    ],
)
def test_tool_argument_metadata_survives_storage_without_executable_arguments(
    db_session: Session,
    conversation: ChatSession,
    raw_arguments: str,
    arguments_complete: bool,
    argument_error: str | None,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.status = RunStatus.CANCELLED
    messages: list[Message] = [
        AssistantMessage(
            content=[
                ToolCall(
                    id="partial",
                    name="search",
                    arguments={},
                    raw_arguments=raw_arguments,
                    arguments_complete=arguments_complete,
                    argument_error=argument_error,
                )
            ]
        )
    ]
    record.steps = _steps(record.run_id, messages, ExecutionStatus(record.status.value))

    _save(db_session, response, record)
    db_session.expire_all()
    assistant = read_response_steps(response)[0].message
    assert isinstance(assistant, AssistantMessage)
    calls = assistant.tool_calls
    assert len(calls) == 1
    assert calls[0].raw_arguments == raw_arguments
    assert calls[0].arguments_complete is arguments_complete
    assert calls[0].argument_error == argument_error
    assert calls[0].arguments == {}


def test_response_item_rejects_mismatched_embedded_identity(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    _save(db_session, response, _record(response))
    row = response.response_items[0]
    row.message = row.message.model_copy(update={"id": "unrelated-message"})
    db_session.flush()
    db_session.expire_all()

    with pytest.raises(ValueError, match="assistant identity"):
        read_response_steps(response)


@pytest.mark.parametrize("removed", ["result", "call"])
def test_response_update_cannot_discard_a_stored_tool_result(
    db_session: Session, conversation: ChatSession, removed: str
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="search", name="search", arguments={})]
            ),
            ToolResultMessage(
                id=f"{record.run_id}:0:result:search",
                tool_call_id="search",
                tool_name="search",
                content="Accepted result",
            ),
        ],
    )
    _save(db_session, response, record)
    changed = record.model_copy(deep=True)
    if removed == "result":
        changed.steps[0].tools["search"].result = None
    else:
        changed.steps[0].message.content = []
        changed.steps[0].tools = {}
    with pytest.raises(ValueError, match="cannot discard recorded results"):
        with db_session.begin_nested():
            save_response_record__no_commit(db_session, response.id, changed)
    db_session.expire_all()
    assert [step.model_dump() for step in read_response_steps(response)] == [
        step.model_dump() for step in record.steps
    ]


@pytest.mark.parametrize("field", ["tool_call_id", "tool_name"])
def test_response_rejects_result_that_does_not_match_invocation(
    db_session: Session, conversation: ChatSession, field: str
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="search-1", name="search", arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="search-1", tool_name="search", content="Found"
            ),
        ],
    )
    _save(db_session, response, record)
    assert response.tool_calls is not None and len(response.tool_calls) == 1
    tool = response.tool_calls[0]
    assert tool.result is not None
    tool.result = tool.result.model_copy(update={field: "unrelated"})
    db_session.flush()
    db_session.expire_all()

    with pytest.raises(ValueError, match="no matching call"):
        read_response_steps(response)


def test_content_free_response_does_not_write_items(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    conversation.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    record = _record(response)
    record.status = RunStatus.ERROR
    record.failure = RunFailure(
        kind=RunFailureKind.EXECUTION, message="Private failure"
    )
    save_response_content(
        response, record, db_session=db_session, persist_content=False
    )
    assert response.response_status == RunStatus.ERROR
    assert response.response_failure is None
    assert (
        execution.response if (execution := read_chat_execution(response)) else None
    ) is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ChatResponseItem)
            .where(ChatResponseItem.chat_message_id == response.id)
        )
        == 0
    )


def test_old_rows_keep_the_legacy_reader(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    response.message = "Existing answer"
    db_session.execute(
        update(ChatMessage)
        .where(ChatMessage.id == response.id)
        .values(
            request_params={
                "model_name": "gpt-5-mini",
                "model_provider": "openai",
                "reasoning_effort": "auto",
                "max_tokens": 1000,
                "sent_kwargs": {},
                "stream": True,
            }
        )
    )
    db_session.commit()
    db_session.expire_all()
    detail = translate_db_message_to_chat_message_detail(response)
    assert detail.message == "Existing answer"
    assert detail.request_params is not None
    assert detail.request_params.model_name == "gpt-5-mini"
    assert "stream" not in detail.request_params.model_dump()
    assert (
        execution.response if (execution := read_chat_execution(response)) else None
    ) is None
    history = convert_chat_history(
        chat_history=capture_chat_history([response], {}, len),
        files=[],
    ).messages
    assert [message.text for message in history] == ["Existing answer"]


def test_regeneration_reuses_user_input_and_preserves_attachments(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    question = response.parent_message
    assert question is not None
    question.files = [
        FileDescriptor(id="attachment", name="source.txt", type=ChatFileType.PLAIN_TEXT)
    ]
    alternate = _response(db_session, conversation, question=question)
    _save(db_session, response, _record(response, "First"))
    _save(db_session, alternate, _record(alternate, "Second"))
    assert response.parent_message_id == alternate.parent_message_id
    assert question.message == "Question"
    assert question.files is not None
    assert question.files[0]["id"] == "attachment"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.chat_session_id == conversation.id,
                ChatMessage.message_type == MessageType.USER,
            )
        )
        == 1
    )


@pytest.mark.parametrize("reverse_save_order", [False, True])
def test_child_reuse_follows_selected_branch_not_completion_order(
    db_session: Session,
    conversation: ChatSession,
    reverse_save_order: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _response(db_session, conversation)
    parent = _record(base)
    child_id = uuid4()
    _child_record(db_session, parent, child_id, "Base")
    _save(db_session, base, parent)
    base_execution = read_chat_execution(base)
    assert base_execution is not None
    previous = base_execution.response.child_runs[0].run_id
    branches = [_response(db_session, conversation, previous=base) for _ in range(2)]
    for index in [1, 0] if reverse_save_order else [0, 1]:
        parent = _record(branches[index])
        _child_record(db_session, parent, child_id, f"Branch {index}", previous)
        _save(db_session, branches[index], parent)
    child = db_session.get(ChatSession, child_id)
    assert child is not None
    monkeypatch.setattr("onyx.db.chat_subagents.MAX_AGENT_HISTORY_RUNS", 2)
    for index, branch in enumerate(branches):
        history = _load_history(
            db_session,
            ChatBranch(
                chat_session_id=conversation.id,
                message_ids=visible_message_ids(db_session, branch),
            ),
            child,
        )
        assert [
            message.text
            for message in history.messages
            if isinstance(message, AssistantMessage)
        ] == [
            "Base",
            f"Branch {index}",
        ]
        assert [
            message.text
            for message in history.messages
            if isinstance(message, UserMessage)
        ] == [
            "Find Base",
            f"Find Branch {index}",
        ]


def test_root_history_and_metadata_do_not_consume_child_history_limit(
    db_session: Session,
    conversation: ChatSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.db.chat_subagents.MAX_AGENT_HISTORY_RUNS", 2)
    monkeypatch.setattr(
        "onyx.db.chat_subagents.get_session_with_current_tenant",
        lambda: nullcontext(db_session),
    )
    first = _response(db_session, conversation)
    record = _record(first)
    child_id = uuid4()
    child = _child_record(db_session, record, child_id, "Child answer")
    _save(db_session, first, record)
    latest = first
    for _ in range(6):
        latest = _response(db_session, conversation, previous=latest)
        _save(db_session, latest, _record(latest))
    restored = chat_subagents.load_agent_history(
        chat_subagents.load_chat_branch(latest.id), str(conversation.id)
    )
    assert restored.previous_run_id == str(latest.id)
    assert sum(isinstance(message, UserMessage) for message in restored.messages) == 7
    assert restored.messages[0].id == f"chat:{first.parent_message_id}"
    restored_child = chat_subagents.load_agent_history(
        chat_subagents.load_chat_branch(latest.id), str(child_id)
    )
    assert restored_child.previous_run_id == child.run_id
    monkeypatch.setattr("onyx.db.chat_subagents.MAX_AGENT_HISTORY_RUNS", 0)
    with pytest.raises(ValueError, match="response limit"):
        chat_subagents.load_agent_history(
            chat_subagents.load_chat_branch(latest.id), str(child_id)
        )
    monkeypatch.setattr("onyx.db.chat_subagents.MAX_AGENT_HISTORY_RUNS", 2)
    metadata = {agent.id: agent for agent in load_session_agent_metadata(latest.id)}
    assert metadata[str(conversation.id)].latest_run_id == str(latest.id)
    assert metadata[str(child_id)].latest_run_id == child.run_id
    assert metadata[str(child_id)].status == RunStatus.COMPLETE
    assert [
        agent.id for agent in load_session_agent_metadata(latest.id, include_root=False)
    ] == [str(child_id)]


@pytest.mark.parametrize("reverse_save_order", [False, True])
def test_nested_child_visibility_and_reuse_follow_root_branch(
    db_session: Session,
    conversation: ChatSession,
    reverse_save_order: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.db.chat_subagents.get_session_with_current_tenant",
        lambda: nullcontext(db_session),
    )
    base = _response(db_session, conversation)
    sibling = _response(db_session, conversation, question=base.parent_message)
    parent = _record(base)
    child_id, grandchild_id = uuid4(), uuid4()
    child_record = _child_record(db_session, parent, child_id, "Child")
    _child_record(
        db_session, child_record, grandchild_id, "Base", path="/root/research/facts"
    )
    _save(db_session, base, parent)
    execution = read_chat_execution(base)
    assert execution is not None
    child_saved = execution.response.child_runs[0]
    grandchild_saved = child_saved.child_runs[0]
    grandchild = db_session.get(ChatSession, grandchild_id)
    assert grandchild is not None
    assert grandchild.spawned_by_message_id == int(child_saved.run_id)
    metadata = {agent.id: agent for agent in load_session_agent_metadata(base.id)}
    assert metadata[str(grandchild_id)].parent_id == str(child_id)
    assert metadata[str(grandchild_id)].path == "/root/research/facts"
    assert [agent.id for agent in load_session_agent_metadata(sibling.id)] == [
        str(conversation.id)
    ]
    for selected, expected in (
        (base, {str(child_id), str(grandchild_id)}),
        (sibling, set()),
    ):
        branch = chat_subagents.load_chat_branch(selected.id)
        assert {
            agent.id
            for agent in load_session_agent_metadata(
                selected.id, branch=branch, include_root=False
            )
        } == expected
    # Only a direct parent can address a child.
    assert (
        lookup_session_agent(
            chat_subagents.load_chat_branch(base.id),
            str(grandchild_id),
            str(conversation.id),
        )
        is None
    )
    descendant = lookup_session_agent(
        chat_subagents.load_chat_branch(base.id), str(grandchild_id), str(child_id)
    )
    assert descendant is not None
    assert descendant.parent_id == str(child_id)
    assert (
        lookup_session_agent(
            chat_subagents.load_chat_branch(base.id), str(child_id), str(grandchild_id)
        )
        is None
    )
    with pytest.raises(ValueError, match="unavailable"):
        lookup_session_agent(
            chat_subagents.load_chat_branch(sibling.id),
            str(grandchild_id),
            str(child_id),
        )

    branches = [_response(db_session, conversation, previous=base) for _ in range(2)]
    for index in [1, 0] if reverse_save_order else [0, 1]:
        parent = _record(branches[index])
        child_record = _child_record(
            db_session, parent, child_id, "Child", child_saved.run_id
        )
        _child_record(
            db_session,
            child_record,
            grandchild_id,
            f"Branch {index}",
            grandchild_saved.run_id,
            path="/root/research/facts",
        )
        _save(db_session, branches[index], parent)
    for index, branch in enumerate(branches):
        history = _load_history(
            db_session,
            ChatBranch(
                chat_session_id=conversation.id,
                message_ids=visible_message_ids(db_session, branch),
            ),
            grandchild,
        )
        assert [
            message.text
            for message in history.messages
            if isinstance(message, AssistantMessage)
        ] == ["Base", f"Branch {index}"]
        assert lookup_session_agent(
            chat_subagents.load_chat_branch(branch.id),
            str(grandchild_id),
            str(child_id),
        )


def test_any_agent_in_the_visible_tree_is_listed_and_addressable(
    db_session: Session, conversation: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "onyx.db.chat_subagents.get_session_with_current_tenant",
        lambda: nullcontext(db_session),
    )
    base = _response(db_session, conversation)
    parent = _record(base)
    child_id, sibling_id, grandchild_id = uuid4(), uuid4(), uuid4()
    child = _child_record(
        db_session, parent, child_id, "Child", tool_name="spawn_agent"
    )
    _child_record(
        db_session,
        child,
        grandchild_id,
        "Leaf",
        path="/root/research/facts",
        tool_name="spawn_agent",
    )
    _save(db_session, base, parent)
    _child_record(db_session, parent, sibling_id, "Sibling", path="/root/review")
    _save(db_session, base, parent)
    for agent_id in (child_id, sibling_id, grandchild_id):
        agent = db_session.get(ChatSession, agent_id)
        assert agent is not None
        agent.restoration_config = ChatConfiguration(kind="chat")
    db_session.flush()
    branch = ChatBranch(chat_session_id=conversation.id, message_ids=[base.id])
    assert {
        info.path: info.parent_id for info in load_session_agent_metadata(base.id)
    } == {
        "/root": None,
        "/root/research": str(conversation.id),
        "/root/review": str(conversation.id),
        "/root/research/facts": str(child_id),
    }

    def send(sender: ResponseRecord, recipient: UUID, text: str) -> ChatInput:
        receipt = enqueue_message(
            db_session,
            branch,
            AgentMessageRequest(
                agent_id=str(recipient),
                parent_id=sender.agent_id or "",
                message=UserMessage(id=str(uuid4()), content=text),
                delivery=MessageDelivery.SEND,
                max_steps=2,
                parent_run_id=sender.run_id,
                parent_message_id=f"{sender.run_id}:0",
                parent_tool_call_id="delegate",
            ),
            base.id,
        )
        row = db_session.scalar(
            select(ChatInput).where(ChatInput.message_id == receipt.id)
        )
        assert row is not None
        return row

    # The root addresses its grandchild; a child addresses its sibling and the root.
    assert send(parent, grandchild_id, "Check").content.startswith(
        "Message from agent /root "
    )
    assert send(child, sibling_id, "Compare").content.startswith(
        "Message from agent /root/research "
    )
    to_root = send(child, conversation.id, "Halfway")
    assert (to_root.target_response_id, to_root.delivery) == (
        None,
        MessageDelivery.SEND,
    )
    # A spawner's instruction keeps its text.
    assert send(parent, child_id, "Continue").content == "Continue"
    with pytest.raises(ValueError, match="cannot message itself"):
        send(child, child_id, "Loop")


@pytest.mark.parametrize("reverse_history", [False, True])
def test_multiple_child_requests_from_one_invocation_keep_distinct_predecessors(
    db_session: Session, conversation: ChatSession, reverse_history: bool
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child_id = uuid4()
    first = _child_record(db_session, parent, child_id, "First")
    _child_record(db_session, parent, child_id, "Second", first.run_id)
    _save(db_session, response, parent)
    execution = read_chat_execution(response)
    assert execution is not None
    first_saved, second_saved = execution.response.child_runs
    generation = execution.response.messages[0]
    assert isinstance(generation, AssistantMessage)
    assert first_saved.parent_message_id == generation.id
    assert execution.tool_records[0].message_id == generation.id
    assert first_saved.run_id != second_saved.run_id
    assert second_saved.previous_run_id == first_saved.run_id
    if reverse_history:
        first_response = db_session.get(ChatMessage, int(first_saved.run_id))
        second_response = db_session.get(ChatMessage, int(second_saved.run_id))
        assert first_response is not None and first_response.parent_message is not None
        assert (
            second_response is not None and second_response.parent_message is not None
        )
        second_response.parent_message.parent_message_id = None
        first_response.parent_message.parent_message_id = second_response.id
        db_session.flush()
        db_session.expire_all()
    child = db_session.get(ChatSession, child_id)
    assert child is not None
    history = _load_history(
        db_session,
        ChatBranch(
            chat_session_id=conversation.id,
            message_ids=visible_message_ids(db_session, response),
        ),
        child,
    )
    assert [
        message.text
        for message in history.messages
        if isinstance(message, AssistantMessage)
    ] == (["Second", "First"] if reverse_history else ["First", "Second"])
    assert history.previous_run_id == (
        first_saved.run_id if reverse_history else second_saved.run_id
    )


def test_child_history_rejects_unrelated_responses_on_the_same_branch(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child_id = uuid4()
    _child_record(db_session, parent, child_id, "First")
    _child_record(db_session, parent, child_id, "Unrelated")
    _save(db_session, response, parent)
    child = db_session.get(ChatSession, child_id)
    assert child is not None
    with pytest.raises(ValueError, match="ambiguous response selection"):
        _load_history(
            db_session,
            ChatBranch(
                chat_session_id=conversation.id,
                message_ids=visible_message_ids(db_session, response),
            ),
            child,
        )


def test_child_publication_rolls_back_with_parent(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child_id = uuid4()
    transaction = db_session.begin_nested()
    _child_record(db_session, parent, child_id, "Answer")
    _save(db_session, response, parent)
    transaction.rollback()
    assert db_session.get(ChatSession, child_id) is None
    assert (
        execution.response if (execution := read_chat_execution(response)) else None
    ) is None


def test_child_multimodal_input_is_rejected_before_child_storage(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child_id = uuid4()
    parent.steps = _steps(
        parent.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            )
        ],
    )
    _save(db_session, response, parent)
    with pytest.raises(ValueError, match="text only"):
        reserve_child_response__no_commit(
            db_session,
            response.id,
            agent=AgentInfo(
                id=str(child_id),
                path="/root/research",
                parent_id=parent.agent_id,
                description="Research child",
                restoration_config=None,
            ),
            instruction=UserMessage(
                content=[
                    ImageContentPart(
                        image_url=ImageUrlDetail(url="https://example.com/image.png")
                    )
                ]
            ),
            previous_response_id=None,
            parent_response_id=int(parent.run_id),
            parent_message_id=f"{parent.run_id}:0",
            parent_tool_call_id="delegate",
            delivers_result=False,
        )
    assert db_session.get(ChatSession, child_id) is None


@pytest.mark.parametrize("summary", ["Summary", ""])
def test_compaction_saves_only_new_output_on_selected_ancestry(
    db_session: Session, conversation: ChatSession, summary: str
) -> None:
    first = _response(db_session, conversation)
    record = _record(first)
    checkpoint = CompactionCheckpoint(
        summary=summary,
        covered_through_message_id=f"chat:{first.parent_message_id}",
    )
    record.checkpoint = checkpoint
    _save(db_session, first, record)
    continued = _response(db_session, conversation, previous=first)
    record = _record(continued)
    record.checkpoint = checkpoint
    _save(db_session, continued, record)
    summaries = list(
        db_session.scalars(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == conversation.id,
                ChatMessage.last_summarized_message_id.is_not(None),
            )
        )
    )
    assert len(summaries) == 1
    assert summaries[0].message_type == MessageType.SUMMARY
    assert summaries[0].message == summary
    assert summaries[0].parent_message_id == first.id
    selected = find_summary_for_ancestry(
        db_session, conversation.id, visible_message_ids(db_session, continued)
    )
    assert checkpoint_from_summary(selected) == checkpoint
    history = _load_history(
        db_session,
        ChatBranch(
            chat_session_id=conversation.id,
            message_ids=visible_message_ids(db_session, continued),
        ),
        conversation,
    )
    assert history.checkpoint == checkpoint
    assert history.messages[0].id == checkpoint.covered_through_message_id
    compacted = working_messages(history.messages, history.checkpoint)
    if summary:
        assert compacted[0].text == f"Conversation summary:\n{summary}"
        assert compacted[1:] == history.messages[1:]
    else:
        assert compacted == history.messages[1:]
    alternate = _response(db_session, conversation)
    assert (
        find_summary_for_ancestry(
            db_session, conversation.id, visible_message_ids(db_session, alternate)
        )
        is None
    )


def test_response_reservation_preserves_model_order_and_active_branch(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    question = response.parent_message
    assert question is not None
    ids = reserve_chat_response_ids(
        db_session, conversation.id, question.id, ["first", "second"]
    )
    responses = [db_session.get(ChatMessage, message_id) for message_id in ids]
    assert [row.model_display_name for row in responses if row] == ["first", "second"]
    assert all(row and row.parent_message_id == question.id for row in responses)
    db_session.refresh(question)
    assert question.latest_child_message_id == ids[-1]


@pytest.mark.parametrize(
    "tool_kind", ["python", "coding", "image", "memory", "search", "search_empty"]
)
def test_completed_tool_display_matches_reload_without_duplicate_streamed_output(
    db_session: Session, conversation: ChatSession, tool_record: Tool, tool_kind: str
) -> None:
    if tool_kind == "python":
        call = ToolCall(
            id="call", name=PythonTool.NAME, arguments={"code": "print('hello')"}
        )
        output = LlmPythonExecutionResult(
            stdout="hello world",
            stderr="warning",
            exit_code=0,
            timed_out=False,
            generated_files=[
                PythonExecutionFile(
                    filename="result.csv", file_link="/api/chat/file/result"
                )
            ],
        )
        result = ToolResult(content=output.model_dump_json(), details=output)
        progress = ToolProgress(
            details=PythonExecutionDelta(stdout="hello world", stderr="warning")
        )
        implementation = PythonTool.__name__
    elif tool_kind == "image":
        call = ToolCall(
            id="call", name=ImageGenerationTool.NAME, arguments={"prompt": "a tree"}
        )
        result = ToolResult(
            content="Generated image",
            details=FinalImageGenerationResponse(
                generated_images=[
                    GeneratedImage(
                        file_id="image-file",
                        url="/api/chat/file/image-file",
                        revised_prompt="A tree in a field",
                        shape="square",
                    )
                ]
            ),
        )
        progress = ToolProgress(details=result.details)
        implementation = ImageGenerationTool.__name__
    elif tool_kind in {"search", "search_empty"}:
        call = ToolCall(
            id="call", name=SearchTool.NAME, arguments={"queries": ["forecast"]}
        )
        document = SearchDoc(
            document_id="forecast-document",
            chunk_ind=0,
            semantic_identifier="Forecast",
            link="https://example.com/forecast",
            blurb="Revenue is rising.",
            source_type=DocumentSource.GOOGLE_DRIVE,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        result = ToolResult(
            content="Revenue is rising.",
            details=SearchDocsResponse(
                queries=["forecast"],
                sources=[DocumentSource.GOOGLE_DRIVE.value],
                search_docs=[document],
                citation_mapping={1: document.document_id},
                displayed_docs=[] if tool_kind == "search_empty" else None,
            ),
        )
        progress = ToolProgress(details=result.details)
        implementation = SearchTool.__name__
    elif tool_kind == "memory":
        call = ToolCall(
            id="call", name=MemoryTool.NAME, arguments={"memory": "Prefers tea"}
        )
        memory = MemoryUpdated(
            memory_text="Prefers tea", operation=MemoryOperation.ADD, memory_id=12
        )
        result = ToolResult(content=memory.model_dump_json(), details=memory)
        progress = ToolProgress(details=result.details)
        implementation = MemoryTool.__name__
    else:
        call = ToolCall(
            id="call",
            name=CodingAgentTool.NAME,
            arguments={"query": "task", "github_repo": "repo"},
        )
        result = ToolResult(
            content="coding answer",
            details=CodingAgentCallResult(answer="coding answer"),
        )
        progress = ToolProgress(details=CodingAgentCallResult(answer="partial answer"))
        implementation = CodingAgentTool.__name__
    session = conversation
    tool = tool_record
    tool.name = call.name
    tool.in_code_tool_id = implementation
    db_session.flush()
    row = _response(db_session, conversation)
    agent_id, run_id = str(session.id), str(row.id)
    snapshot = RunState(
        agent_id=agent_id,
        run_id=run_id,
        status=RunStatus.COMPLETE,
        input_messages=[UserMessage(content="Question")],
        answer_step_index=1,
        steps=[
            StepRecord(
                message=AssistantMessage(id="stable-generation", content=[call]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    call.id: ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_call_id=call.id,
                            tool_name=call.name,
                            content=result.content,
                            details=result.details,
                        ),
                    )
                },
            ),
            StepRecord(
                message=AssistantMessage(
                    id="final-generation", content=[TextContent(text="done")]
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={},
            ),
        ],
    )
    db_session.commit()
    queue: Queue[Packet] = Queue()
    presenter = ResponsePresenter(Emitter(queue.put_nowait))
    presenter.consume(
        MessageStartEvent(run_id=run_id, message_id="stable-generation", step_index=0)
    )
    presenter.consume(
        MessageEndEvent(
            run_id=run_id,
            message_id="stable-generation",
            step_index=0,
            message=snapshot.steps[0].message,
            status=ExecutionStatus.COMPLETE,
        )
    )
    presenter.consume(
        ToolStartEvent(
            run_id=run_id, message_id="stable-generation", step_index=0, tool_call=call
        )
    )
    presenter.consume(
        ToolUpdateEvent(
            run_id=run_id,
            message_id="stable-generation",
            step_index=0,
            tool_call=call,
            progress=progress,
        )
    )
    presenter.consume(
        ToolEndEvent(
            run_id=run_id,
            message_id="stable-generation",
            step_index=0,
            tool_call=call,
            result=result,
        )
    )
    live: list[Packet] = []
    while not queue.empty():
        packet = queue.get_nowait()
        assert isinstance(packet, Packet)
        live.append(packet)
    projected = project_response(snapshot, tool_ids={call.name: tool.id})
    get_chat_history_store(
        message_id=row.id, chat_session_id=conversation.id, persist_content=True
    ).save_response(projected)
    db_session.expire_all()
    assert read_chat_execution(row) is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(StoredToolCall)
            .where(StoredToolCall.parent_chat_message_id == row.id)
        )
        == 1
    )
    db_session.delete(tool)
    db_session.commit()
    saved = translate_assistant_message_to_packets(
        row, load_session_tools([row], db_session), db_session
    )
    if tool_kind == "python":
        live_stdout = "".join(
            packet.obj.stdout
            for packet in live
            if isinstance(packet.obj, PythonToolDelta)
        )
        saved_stdout = "".join(
            packet.obj.stdout
            for packet in saved
            if isinstance(packet.obj, PythonToolDelta)
        )
        assert live_stdout == saved_stdout == "hello world"
        for packets in (live, saved):
            assert (
                "".join(
                    packet.obj.stderr
                    for packet in packets
                    if isinstance(packet.obj, PythonToolDelta)
                )
                == "warning"
            )
            assert [
                file_id
                for packet in packets
                if isinstance(packet.obj, PythonToolDelta)
                for file_id in packet.obj.file_ids
            ] == ["result"]
    elif tool_kind == "image":
        for packets in (live, saved):
            images = [
                image.model_dump()
                for packet in packets
                if isinstance(packet.obj, ImageGenerationFinal)
                for image in packet.obj.images
            ]
            assert images == [
                {
                    "file_id": "image-file",
                    "url": "/api/chat/file/image-file",
                    "revised_prompt": "A tree in a field",
                    "shape": "square",
                }
            ]
    elif tool_kind in {"search", "search_empty"}:
        for packets in (live, saved):
            documents = [
                document
                for packet in packets
                if isinstance(packet.obj, SearchToolDocumentsDelta)
                for document in packet.obj.documents
            ]
            assert [
                (document.document_id, document.link, document.blurb)
                for document in documents
            ] == (
                []
                if tool_kind == "search_empty"
                else [
                    (
                        "forecast-document",
                        "https://example.com/forecast",
                        "Revenue is rising.",
                    )
                ]
            )
            assert [
                query
                for packet in packets
                if isinstance(packet.obj, SearchToolQueriesDelta)
                for query in packet.obj.queries
            ] == ["forecast"]
        assert len(row.search_docs) == 1
    elif tool_kind == "memory":
        for packets in (live, saved):
            memories = [
                packet.obj
                for packet in packets
                if isinstance(packet.obj, MemoryToolDelta)
            ]
            assert len(memories) == 1
            assert memories[0].memory_text == "Prefers tea"
            assert memories[0].operation == "add"
            assert memories[0].memory_id == 12
    else:
        live_answers = [
            packet.obj.answer
            for packet in live
            if isinstance(packet.obj, CodingAgentFinal)
        ]
        saved_answers = [
            packet.obj.answer
            for packet in saved
            if isinstance(packet.obj, CodingAgentFinal)
        ]
        assert live_answers[-1] == saved_answers[-1] == "coding answer"


def test_new_summary_replaces_previous_summary_on_selected_branch(
    db_session: Session, conversation: ChatSession
) -> None:
    base = _response(db_session, conversation)
    previous_summary = ChatMessage(
        chat_session_id=conversation.id,
        parent_message_id=base.id,
        last_summarized_message_id=f"chat:{base.parent_message_id}",
        message="Previous summary",
        message_type=MessageType.SUMMARY,
        token_count=2,
    )
    db_session.add(previous_summary)
    db_session.flush()
    response = _response(db_session, conversation, previous=base)
    record = _record(response)
    record.checkpoint = CompactionCheckpoint(
        summary="Updated summary",
        covered_through_message_id=f"chat:{response.parent_message_id}",
    )
    _save(db_session, response, record)
    ancestry = visible_message_ids(db_session, response)
    exact = find_summary_for_ancestry(db_session, conversation.id, ancestry)
    assert checkpoint_from_summary(exact) == record.checkpoint
    baseline = find_summary_for_ancestry(
        db_session, conversation.id, visible_message_ids(db_session, base)
    )
    assert baseline is not None and baseline.id == previous_summary.id


def test_session_delete_removes_reused_child_history_and_tool_items(
    db_session: Session, conversation: ChatSession
) -> None:
    base = _response(db_session, conversation)
    record = _record(base)
    child_id = uuid4()
    child = _child_record(db_session, record, child_id, "First")
    grandchild_id = uuid4()
    _child_record(db_session, child, grandchild_id, "Nested")
    _save(db_session, base, record)
    first = read_chat_execution(base)
    assert first is not None
    next_response = _response(db_session, conversation, previous=base)
    record = _record(next_response)
    _child_record(
        db_session,
        record,
        child_id,
        "Second",
        first.response.child_runs[0].run_id,
    )
    _save(db_session, next_response, record)
    descendant_ids = [child_id, grandchild_id]
    response_ids = list(
        db_session.scalars(
            select(ChatMessage.id).where(
                ChatMessage.chat_session_id.in_([conversation.id, *descendant_ids])
            )
        )
    )
    delete_chat_session(None, conversation.id, db_session, hard_delete=True)
    assert (
        db_session.scalar(
            select(ChatSession.id).where(ChatSession.id.in_(descendant_ids))
        )
        is None
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.chat_session_id.in_(descendant_ids))
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ChatResponseItem)
            .where(ChatResponseItem.chat_message_id.in_(response_ids))
        )
        == 0
    )


@pytest.mark.parametrize("unfinished_child", [False, True])
@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.SUSPENDED])
def test_unsettled_execution_is_rejected_before_saving(
    db_session: Session,
    status: RunStatus,
    conversation: ChatSession,
    unfinished_child: bool,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    if unfinished_child:
        child = _child_record(db_session, record, uuid4(), "Partial child output")
        child.status = status
        record.child_runs = [child]
    else:
        record.status = status
    original_status = response.response_status
    original_items = list(response.response_items)
    with pytest.raises(ValueError, match="terminal execution records"):
        _save(db_session, response, record)
    assert response.response_status == original_status
    assert response.response_items == original_items


@pytest.mark.parametrize("child_count", [0, 1, 4])
@pytest.mark.parametrize("reuse_branch", [False, True])
def test_discovery_batches_response_metadata(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
    monkeypatch: pytest.MonkeyPatch,
    child_count: int,
    reuse_branch: bool,
) -> None:
    monkeypatch.setattr(
        "onyx.db.chat_subagents.get_session_with_current_tenant",
        lambda: nullcontext(db_session),
    )
    response = _response(db_session, conversation)
    record = _record(response)
    for index in range(child_count):
        _child_record(
            db_session,
            record,
            uuid4(),
            f"Answer {index}",
            path=f"/root/research_{index}",
        )
    _save(db_session, response, record)
    message_id = response.id
    db_session.expire_all()
    branch = chat_subagents.load_chat_branch(message_id)
    executed_sql.clear()

    if reuse_branch:
        metadata = load_session_agent_metadata(
            message_id, branch=branch, include_root=False
        )
        assert len(executed_sql) == (3 if child_count else 1)
    else:
        metadata = load_session_agent_metadata(message_id)

    assert len(metadata) == child_count + (not reuse_branch)
    assert all(agent.latest_run_id is not None for agent in metadata)
    assert sum(
        "WITH RECURSIVE selected_responses" in query for query in executed_sql
    ) == (2 if child_count else 1)
    assert sum(
        "WITH RECURSIVE session_ancestors" in query for query in executed_sql
    ) == bool(child_count)
    assert not any("chat_response_item" in query for query in executed_sql)


@pytest.mark.parametrize("child_count", [1, 4])
def test_coordinator_discovery_reads_no_content_or_inbox(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
    child_count: int,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    for index in range(child_count):
        child = _child_record(
            db_session,
            record,
            uuid4(),
            f"Answer {index}",
            path=f"/root/research_{index}",
        )
        if index == 0:
            child.status = RunStatus.LIMIT
    _save(db_session, response, record)
    session_id = conversation.id
    response_id = response.id
    branch = ChatBranch(chat_session_id=session_id, message_ids=[response_id])
    for child in record.child_runs:
        child_row = db_session.get(ChatMessage, int(child.run_id))
        assert child_row is not None and child.agent_id is not None
        child_row.chat_session.restoration_config = ChatConfiguration(kind="chat")
        enqueue_message(
            db_session,
            branch,
            AgentMessageRequest(
                agent_id=child.agent_id,
                parent_id=str(session_id),
                message=UserMessage(content=f"Follow up {child.agent_path}"),
                delivery=MessageDelivery.QUEUE,
                max_steps=3,
                parent_run_id=record.run_id,
                parent_message_id=f"{record.run_id}:0",
                parent_tool_call_id="delegate",
            ),
            response_id,
        )
    db_session.commit()
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    store = ChatRunStore(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=session_id,
        response_id=response_id,
        visible_response_ids=[response_id],
        cache=cache,
        follow_up_steps=4,
        control_cache=cache,
    )
    coordinator = AgentCoordinator(directory=store)
    executed_sql.clear()

    agents = coordinator.discover_agents()
    children = [agent for agent in agents if agent.parent_id is not None]

    # Sessions, the root's latest response, ancestry, and child responses.
    assert len(executed_sql) == 4
    assert len(agents) == child_count + 1
    assert len(children) == child_count
    assert not any("chat_response_item" in query for query in executed_sql)
    assert not any("chat_input" in query for query in executed_sql)


def test_child_reload_batches_siblings(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
) -> None:
    query_counts: list[int] = []
    for child_count in (1, 6):
        response = _response(db_session, conversation)
        record = _record(response)
        for index in range(child_count):
            _child_record(
                db_session,
                record,
                uuid4(),
                f"Answer {index}",
                path=f"/root/research_{index}",
            )
        _save(db_session, response, record)
        db_session.expire_all()
        executed_sql.clear()

        execution = read_chat_execution(response)

        assert execution is not None
        assert len(execution.response.child_runs) == child_count
        assert [child.agent_path for child in execution.response.child_runs] == [
            f"/root/research_{index}" for index in range(child_count)
        ]
        query_counts.append(len(executed_sql))
    assert query_counts[0] == query_counts[1]


def test_nested_reload_reuses_parent_identity(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    child = _child_record(db_session, record, uuid4(), "Child")
    _child_record(db_session, child, uuid4(), "Grandchild", path="/root/research/facts")
    _save(db_session, response, record)
    db_session.expire_all()
    executed_sql.clear()

    execution = read_chat_execution(response)

    assert execution is not None
    saved_child = execution.response.child_runs[0]
    saved_grandchild = saved_child.child_runs[0]
    parent_message = record.messages[0]
    child_message = child.messages[0]
    assert isinstance(parent_message, AssistantMessage)
    assert isinstance(child_message, AssistantMessage)
    assert saved_child.parent_message_id == parent_message.id
    assert saved_grandchild.parent_message_id == child_message.id
    assert saved_grandchild.agent_path == "/root/research/facts"
    assert (
        sum("WITH RECURSIVE session_ancestors" in query for query in executed_sql) == 0
    )


def test_plain_history_reload_query_count_does_not_grow_per_turn(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
) -> None:
    session_id = conversation.id
    previous = None
    answers: list[str] = []
    query_counts: list[int] = []
    for turn_count in (1, 10):
        while len(answers) < turn_count:
            answer = f"Answer {len(answers)}"
            response = _response(db_session, conversation, previous=previous)
            _save(db_session, response, _record(response, answer))
            answers.append(answer)
            previous = response
        db_session.expire_all()
        executed_sql.clear()

        messages = get_chat_messages_by_session(
            session_id,
            None,
            db_session,
            skip_permission_check=True,
            prefetch_message_details=True,
        )
        replayed = [
            "".join(
                packet.obj.content
                for packet in translate_assistant_message_to_packets(
                    message, load_session_tools([message], db_session), db_session
                )
                if isinstance(packet.obj, AgentResponseDelta)
            )
            for message in messages
            if message.message_type == MessageType.ASSISTANT
        ]
        assert replayed == answers
        query_counts.append(len(executed_sql))

    assert query_counts[0] == query_counts[1]


def test_public_message_read_does_not_fetch_response_items(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
) -> None:
    response = _response(db_session, conversation)
    _save(db_session, response, _record(response))
    message_id = response.id
    db_session.expire_all()
    executed_sql.clear()

    message = get_chat_message(message_id, None, db_session)

    assert message.id == message_id
    assert not any("chat_response_item" in query for query in executed_sql)


def test_history_loads_items_only_for_selected_ancestry(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
) -> None:
    root = get_or_create_root_message(conversation.id, db_session)
    selected = _response(db_session, conversation, previous=root)
    question = selected.parent_message
    assert question is not None
    root.latest_child_message_id = question.id
    question.latest_child_message_id = selected.id
    sibling = _response(db_session, conversation, question=question)
    later = _response(db_session, conversation, previous=selected)
    assert later.parent_message is not None
    selected.latest_child_message_id = later.parent_message.id
    later.parent_message.latest_child_message_id = later.id
    for response in (selected, sibling, later):
        _save(db_session, response, _record(response))
    selected_id = selected.id
    session_id = conversation.id
    db_session.expire_all()
    executed_sql.clear()

    history, parent = load_message_branch(session_id, selected_id, db_session)

    assert parent.id == selected_id
    assert [message.id for message in history] == [question.id, selected_id]
    assert selected.response_items
    assert "response_items" in inspect(sibling).unloaded
    assert "response_items" in inspect(later).unloaded
    assert "tool_calls" in inspect(sibling).unloaded
    assert "tool_calls" in inspect(later).unloaded
    assert sum("FROM chat_response_item" in query for query in executed_sql) == 1
    assert "search_docs" not in inspect(selected).unloaded
    executed_sql.clear()
    capture_chat_history(history, {}, len)
    assert not any("search_doc" in query for query in executed_sql)


@pytest.mark.parametrize("invalid_character", ["\x00", "\ud800"])
def test_response_storage_sanitizes_postgres_text_without_mutating_input(
    db_session: Session,
    conversation: ChatSession,
    invalid_character: str,
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    original_text = f"before{invalid_character}after"
    messages: list[Message] = [
        AssistantMessage(
            content=[
                TextContent(text=original_text),
                ToolCall(
                    id="search", name="search", arguments={"query": original_text}
                ),
            ]
        ),
        ToolResultMessage(
            tool_call_id="search",
            tool_name="search",
            content=original_text,
            details=CustomToolCallSummary(
                tool_name="search",
                response_type="json",
                tool_result={"text": original_text},
            ),
        ),
        AssistantMessage(content=[TextContent(text=original_text)]),
    ]
    record.steps = _steps(record.run_id, messages, ExecutionStatus(record.status.value))

    record.answer_step_index = 1
    original = record.model_copy(deep=True)

    _save(db_session, response, record)

    replay = messages_from_steps(read_response_steps(response))
    assert [message.text for message in replay] == ["beforeafter"] * 3
    first = replay[0]
    assert isinstance(first, AssistantMessage)
    assert first.tool_calls[0].arguments == {"query": "beforeafter"}
    result = replay[1]
    assert isinstance(result, ToolResultMessage)
    assert isinstance(result.details, CustomToolCallSummary)
    assert result.details.tool_result == {"text": "beforeafter"}
    assert record == original


@pytest.mark.parametrize(
    "save_order", ["lifecycle_first", "display_first", "concurrent"]
)
@pytest.mark.parametrize(
    "status", [RunStatus.COMPLETE, RunStatus.ERROR, RunStatus.CANCELLED]
)
def test_lifecycle_and_display_saves_share_response_content(
    db_session: Session, conversation: ChatSession, save_order: str, status: RunStatus
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    child_id = uuid4()
    child = _child_record(db_session, record, child_id, "Child answer")
    record.status = status
    child.checkpoint = CompactionCheckpoint(
        summary="Child summary",
        covered_through_message_id=f"run:{child.run_id}:input:0",
    )
    root_id = response.id
    root_session_id = conversation.id
    initial = record.model_copy(
        update={
            "answer_step_index": None,
            "child_runs": [],
            "status": RunStatus.RUNNING,
        }
    )
    save_response_record__no_commit(db_session, root_id, initial)
    db_session.commit()
    try:
        display = ChatResponseSnapshot(
            answer="Answer",
            reasoning=None,
            request_params=None,
            citation_to_doc={},
            tool_calls=[],
            is_clarification=False,
            all_search_docs={},
            pre_answer_processing_time=None,
            response=record,
            cancelled=status == RunStatus.CANCELLED,
        )
        barrier = threading.Barrier(2) if save_order == "concurrent" else None
        engine = db_session.get_bind()

        def save_lifecycle() -> None:
            if barrier is not None:
                barrier.wait(timeout=10)
            with Session(engine) as session:
                check_checkpoint_owner__no_commit(session, root_id, None)
                save_response_record__no_commit(
                    session, root_id, record.model_copy(update={"child_runs": []})
                )
                save_response_record__no_commit(session, root_id, child)
                session.commit()

        def save_display() -> None:
            if barrier is not None:
                barrier.wait(timeout=10)
            get_chat_history_store(
                message_id=root_id,
                chat_session_id=root_session_id,
                persist_content=True,
            ).save_response(display)

        if save_order == "concurrent":
            lifecycle = start_thread_future(save_lifecycle, name="test-lifecycle-save")
            presentation = start_thread_future(save_display, name="test-display-save")
            lifecycle.result(timeout=20)
            presentation.result(timeout=20)
        elif save_order == "lifecycle_first":
            save_lifecycle()
            save_display()
        else:
            save_display()
            save_lifecycle()
        db_session.expire_all()
        saved_root = db_session.get(ChatMessage, root_id)
        assert saved_root is not None
        assert saved_root.message == (
            "Answer ... \n\nGeneration was stopped by the user."
            if status == RunStatus.CANCELLED
            else "Answer"
        )
        assert saved_root.response_status == status
        assert read_response_steps(saved_root) == record.steps
        saved_child = read_response__no_commit(db_session, int(child.run_id))
        assert saved_child is not None
        assert saved_child.response.parent_run_id == record.run_id
        assert saved_child.response.checkpoint == child.checkpoint
        assert saved_child.response.input_messages == child.input_messages
        assert saved_child.response.messages == child.messages
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(ChatSession.spawned_by_message_id == root_id)
            )
            == 1
        )
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(StoredToolCall)
                .where(StoredToolCall.chat_session_id == root_session_id)
            )
            == 1
        )
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .where(
                    ChatMessage.chat_session_id == child_id,
                    ChatMessage.message_type == MessageType.SUMMARY,
                )
            )
            == 1
        )
    finally:
        db_session.rollback()
        delete_messages_and_files_from_chat_session(root_session_id, db_session)
        db_session.commit()


@pytest.mark.parametrize("large_field", ["question", "item", "tool"])
def test_history_size_checks_all_payloads_in_one_query(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
    monkeypatch: pytest.MonkeyPatch,
    large_field: str,
) -> None:
    response = _response(
        db_session, conversation, text="x" * 2000 if large_field == "question" else ""
    )
    record = _record(response)
    messages: list[Message] = [
        AssistantMessage(
            content=[
                TextContent(text="x" * 2000 if large_field == "item" else ""),
                ToolCall(id="call", name="search", arguments={}),
            ]
        ),
        ToolResultMessage(
            tool_call_id="call",
            tool_name="search",
            content="x" * 2000 if large_field == "tool" else "",
        ),
    ]
    record.steps = _steps(record.run_id, messages, ExecutionStatus(record.status.value))

    _save(db_session, response, record)
    response_id = response.id
    monkeypatch.setattr(chat_subagents, "MAX_AGENT_HISTORY_BYTES", 1000)
    executed_sql.clear()
    with pytest.raises(ValueError, match="history exceeds its content limit"):
        chat_subagents._check_history_size(db_session, [response_id])
    assert len(executed_sql) == 1
    monkeypatch.setattr(chat_subagents, "MAX_AGENT_HISTORY_BYTES", 10000)
    chat_subagents._check_history_size(db_session, [response_id])
    chat_subagents._check_history_size(db_session, [])


@pytest.mark.parametrize("mismatch", ["session", "recording_mode"])
def test_response_store_rejects_wrong_session_or_recording_mode_before_writes(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
    mismatch: str,
) -> None:
    conversation.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    row = _response(db_session, conversation)
    message_id, session_id = row.id, conversation.id
    db_session.commit()
    response = ChatResponseSnapshot(
        answer="private answer",
        response=None,
        reasoning=None,
        request_params=None,
        citation_to_doc={},
        tool_calls=[],
        is_clarification=False,
        all_search_docs={},
        pre_answer_processing_time=None,
        cancelled=False,
    )
    executed_sql.clear()
    expected_error = (
        "another chat session" if mismatch == "session" else "recording mode"
    )
    with pytest.raises(ValueError, match=expected_error):
        save_chat_response_to_db(
            message_id=message_id,
            chat_session_id=uuid4() if mismatch == "session" else session_id,
            expected_persist_content=mismatch == "recording_mode",
            response=response,
        )
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in executed_sql
    )
    db_session.refresh(row)
    assert row.message == ""
    assert row.error is None
    assert not row.response_items


@pytest.mark.parametrize("reserve_child", [False, True])
def test_content_free_sessions_reject_incremental_content_writes(
    db_session: Session, conversation: ChatSession, reserve_child: bool
) -> None:
    conversation.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    response = _response(db_session, conversation, text="")
    db_session.commit()
    record = _record(response, answer="must not be stored")
    child_id = uuid4()
    with pytest.raises(ValueError, match="Content-free"):
        if reserve_child:
            reserve_child_response__no_commit(
                db_session,
                response.id,
                agent=AgentInfo(
                    id=str(child_id),
                    path="/root/child",
                    parent_id=str(conversation.id),
                    description="private",
                    restoration_config=None,
                ),
                instruction=UserMessage(content="private instruction"),
                previous_response_id=None,
                parent_response_id=response.id,
                parent_message_id="message",
                parent_tool_call_id="call",
                delivers_result=False,
            )
        else:
            save_response_record__no_commit(db_session, response.id, record)
    db_session.commit()
    db_session.expire_all()
    assert response.message == ""
    assert not response.response_items
    assert not response.tool_calls
    assert response.response_status is None
    assert db_session.get(ChatSession, child_id) is None


def test_legacy_rows_keep_tool_results_and_display_text(
    db_session: Session, conversation: ChatSession, tool_record: Tool
) -> None:
    response = _response(db_session, conversation)
    response.message = "Existing answer"
    response.reasoning_tokens = "Existing thinking"
    db_session.add(
        StoredToolCall(
            chat_session_id=conversation.id,
            parent_chat_message_id=response.id,
            turn_number=0,
            tab_index=0,
            tool_id=tool_record.id,
            tool_call_id="legacy-call",
            reasoning_tokens="Tool thinking",
            tool_call_arguments={"query": "cedar"},
            legacy_response="Existing result",
            tool_call_tokens=1,
            result=None,
        )
    )
    db_session.commit()
    db_session.expire_all()
    saved = db_session.get(ChatMessage, response.id)
    assert saved is not None
    assert saved.message == "Existing answer"
    assert saved.reasoning_tokens == "Existing thinking"
    assert saved.response_status is None
    assert saved.response_items == []
    assert read_chat_execution(saved) is None
    tool = db_session.scalar(
        select(StoredToolCall).where(
            StoredToolCall.parent_chat_message_id == response.id
        )
    )
    assert tool is not None
    assert tool.tool_call_response == "Existing result"
    assert tool.result is None
    assert (
        db_session.scalar(
            select(StoredToolCall.legacy_response).where(StoredToolCall.id == tool.id)
        )
        == "Existing result"
    )


def test_projected_response_round_trip_replays_tool_and_answer(
    db_session: Session, conversation: ChatSession, tool_record: Tool
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[
                    ToolCall(
                        id="remember", name="memory", arguments={"text": "Prefers tea"}
                    )
                ]
            ),
            ToolResultMessage(
                tool_call_id="remember",
                tool_name="memory",
                content="Saved preference",
                details=MemoryUpdated(
                    memory_text="Prefers tea",
                    operation=MemoryOperation.ADD,
                    memory_id=7,
                ),
            ),
            AssistantMessage(content=[TextContent(text="I saved your preference.")]),
        ],
    )
    record.answer_step_index = 1
    snapshot = RunState(
        run_id=record.run_id,
        agent_id=record.agent_id,
        status=RunStatus.COMPLETE,
        input_messages=record.input_messages,
        steps=record.steps,
        answer_step_index=1,
    )
    projected = project_response(snapshot, tool_ids={"memory": tool_record.id})
    assert projected.error is None
    message_id, session_id = response.id, conversation.id
    db_session.commit()
    assert (
        save_chat_response_to_db(
            message_id=message_id,
            chat_session_id=session_id,
            expected_persist_content=True,
            response=projected,
        )
        == "I saved your preference."
    )
    db_session.expire_all()
    stored = db_session.get(ChatMessage, message_id)
    assert stored is not None
    execution = read_chat_execution(stored)
    assert execution is not None
    assert [step.model_dump() for step in execution.response.steps] == [
        step.model_dump() for step in record.steps
    ]
    assert len(execution.tool_records) == 1
    replay = read_response_replay_data(execution, db_session)
    packets = replay_response(
        execution.response, replay.tools, execution.presentation, replay.documents
    )
    assert (
        "".join(
            packet.obj.content
            for packet in packets
            if isinstance(packet.obj, AgentResponseDelta)
        )
        == "I saved your preference."
    )
    memory = [
        packet.obj for packet in packets if isinstance(packet.obj, MemoryToolDelta)
    ]
    assert len(memory) == 1
    assert memory[0].memory_text == "Prefers tea"
    assert memory[0].memory_id == 7
    assert memory[0].operation == "add"


def test_search_projection_restores_saved_source_cards(
    db_session: Session, conversation: ChatSession, tool_record: Tool
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    document = SearchDoc(
        document_id="cedar-doc",
        chunk_ind=0,
        semantic_identifier="Cedar guide",
        blurb="Cedar facts",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[
                    ToolCall(
                        id="search",
                        name="internal_search",
                        arguments={"query": "cedar"},
                    )
                ]
            ),
            ToolResultMessage(
                tool_call_id="search",
                tool_name="internal_search",
                content="Cedar facts",
                details=SearchDocsResponse(
                    search_docs=[document], citation_mapping={1: document.document_id}
                ),
            ),
            AssistantMessage(content=[TextContent(text="Cedar is a tree.")]),
        ],
    )
    projected = project_response(
        RunState(
            run_id=record.run_id,
            agent_id=record.agent_id,
            status=RunStatus.COMPLETE,
            input_messages=record.input_messages,
            steps=record.steps,
            answer_step_index=1,
        ),
        tool_ids={"internal_search": tool_record.id},
    )
    assert projected.error is None
    message_id, session_id = response.id, conversation.id
    db_session.commit()
    save_chat_response_to_db(
        message_id=message_id,
        chat_session_id=session_id,
        expected_persist_content=True,
        response=projected,
    )
    db_session.expire_all()
    stored = db_session.get(ChatMessage, message_id)
    assert stored is not None
    execution = read_chat_execution(stored)
    assert execution is not None
    replay = read_response_replay_data(execution, db_session)
    saved_document = replay.documents[document.document_id]
    assert isinstance(saved_document, SavedSearchDoc)
    assert saved_document.db_doc_id > 0
    packets = replay_response(
        execution.response, replay.tools, execution.presentation, replay.documents
    )
    cards = [
        packet.obj
        for packet in packets
        if isinstance(packet.obj, SearchToolDocumentsDelta)
    ]
    assert len(cards) == 1
    assert cards[0].documents == [saved_document]
    assert (
        "".join(
            packet.obj.content
            for packet in packets
            if isinstance(packet.obj, AgentResponseDelta)
        )
        == "Cedar is a tree."
    )
    # Model history must recover uncited evidence as well as displayed citations.
    assert not stored.citations
    captured = capture_chat_history([stored], {}, len)
    restored_result = next(
        message
        for entry in captured
        for message in entry.response_messages
        if isinstance(message, ToolResultMessage)
    )
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(message_citation_sources(restored_result))
    assert processor.get_next_citation_number() == 2
    assert isinstance(restored_result.details, SearchDocsResponse)
    assert restored_result.details.search_docs == [saved_document]
    assert restored_result.details.citation_mapping == {1: document.document_id}
    assert stored.tool_calls is not None
    stored_result = stored.tool_calls[0].result
    assert stored_result is not None
    assert isinstance(stored_result.details, SearchDocsResponse)
    assert stored_result.details.search_docs == []

    reference = execution.tool_records[0]
    assert (
        replay.tools[(reference.message_id, reference.tool_call_id)].tool_id
        == tool_record.id
    )
    invalid = execution.model_copy(deep=True)
    invalid.tool_records[0].message_id = "unrelated-message"
    with pytest.raises(ValueError, match="not part of this response"):
        read_response_replay_data(invalid, db_session)


def test_child_usage_is_reported_with_root_attribution(
    db_session: Session, conversation: ChatSession
) -> None:
    user = User(
        id=uuid4(), email=f"usage-{uuid4()}@example.com", hashed_password="unused"
    )
    db_session.add(user)
    db_session.flush()
    conversation.user_id = user.id
    conversation.onyxbot_flow = True
    root = _response(db_session, conversation)
    record = _record(root)
    child = _child_record(db_session, record, uuid4(), "Child answer")
    _save(db_session, root, record)
    db_session.commit()
    try:
        child_session = db_session.get(ChatSession, UUID(child.agent_id or ""))
        assert child_session is not None
        assert child_session.user_id == user.id
        assert child_session.persona_id == conversation.persona_id
        assert child_session.onyxbot_flow is True
        _, entries = get_empty_chat_messages_entries__paginated(
            db_session,
            (
                datetime.now(timezone.utc) - timedelta(days=1),
                datetime.now(timezone.utc) + timedelta(days=1),
            ),
            limit=None,
        )
        child_entries = [
            entry for entry in entries if entry.chat_session_id == child_session.id
        ]
        assert len(child_entries) == 1
        assert child_entries[0].user_id == str(user.id)
        assert child_entries[0].user_email == user.email
        assert child_entries[0].flow_type == FlowType.SLACK
        assert child_entries[0].number_of_tokens > 0
    finally:
        db_session.rollback()
        db_session.delete(user)
        db_session.commit()


def test_mixed_legacy_and_canonical_history_preserves_each_saved_format(
    db_session: Session, conversation: ChatSession, tool_record: Tool
) -> None:
    legacy = _response(db_session, conversation, text="Old question")
    legacy.message = "Old answer"
    legacy_call = StoredToolCall(
        chat_session_id=conversation.id,
        parent_chat_message_id=legacy.id,
        turn_number=0,
        tab_index=0,
        tool_id=tool_record.id,
        tool_call_id="old-call",
        tool_call_arguments={"query": "old"},
        legacy_response="Old actual tool output",
        tool_call_tokens=1,
        result=None,
    )
    db_session.add(legacy_call)
    current = _response(db_session, conversation, text="New question", previous=legacy)
    record = _record(current, "New answer")
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="new-call", name="lookup", arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="new-call",
                tool_name="lookup",
                content="New actual tool output",
            ),
            AssistantMessage(content=[TextContent(text="New answer")]),
        ],
    )
    record.answer_step_index = 1
    _save(db_session, current, record)
    db_session.commit()
    db_session.expire_all()

    history = capture_chat_history([legacy, current], {tool_record.id: "lookup"}, len)
    old_results = [
        m for m in history[0].response_messages if isinstance(m, ToolResultMessage)
    ]
    new_results = [
        m for m in history[1].response_messages if isinstance(m, ToolResultMessage)
    ]
    assert [m.text for m in old_results] == ["Old actual tool output"]
    assert [m.text for m in new_results] == ["New actual tool output"]
    assert legacy_call.result is None
    assert legacy_call.tool_call_response == "Old actual tool output"
    assert (
        db_session.scalar(
            select(StoredToolCall.legacy_response).where(
                StoredToolCall.id == legacy_call.id
            )
        )
        == "Old actual tool output"
    )
    assert not legacy.response_items
    assert current.response_items


def test_replay_sources_include_tool_documents_and_preserve_root_versions(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.steps = _steps(
        record.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="search", name="internal_search", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="Answer")]),
        ],
    )
    record.answer_step_index = 1
    _save(db_session, response, record)
    documents = [
        StoredSearchDoc(
            document_id=document_id,
            chunk_ind=0,
            semantic_id="Guide",
            blurb=version,
            boost=1,
            source_type=DocumentSource.WEB,
            hidden=False,
            doc_metadata={},
            score=1.0,
            match_highlights=[],
        )
        for document_id, version in (
            ("shared", "root version"),
            ("shared", "tool version"),
            ("tool-only", "tool-only source"),
        )
    ]
    db_session.add_all(documents)
    response.search_docs = documents[:1]
    assert response.tool_calls is not None
    response.tool_calls[0].search_docs = documents[1:]
    db_session.flush()
    db_session.expire_all()

    execution = read_chat_execution(response)
    assert execution is not None
    replay = read_response_replay_data(execution, db_session)
    assert {key: doc.blurb for key, doc in replay.documents.items()} == {
        "shared": "root version",
        "tool-only": "tool-only source",
    }
    reference = execution.tool_records[0]
    assert [
        doc.blurb
        for doc in replay.tools[
            (reference.message_id, reference.tool_call_id)
        ].search_docs
    ] == ["tool version", "tool-only source"]


@pytest.mark.parametrize("existing_checkpoint", [False, True])
@pytest.mark.parametrize("rejection", ["content_free", "response_binding"])
def test_invalid_checkpoint_publication_leaves_state_unchanged(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
    existing_checkpoint: bool,
    rejection: str,
) -> None:
    if rejection == "content_free":
        conversation.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    response = _response(db_session, conversation, text="")
    response.response_status = RunStatus.RUNNING
    if existing_checkpoint:
        db_session.add(
            ChatResponseCheckpoint(
                chat_message_id=response.id, ownership_version=1, state={}
            )
        )
    db_session.commit()
    checkpoint = ResponseCheckpoint(
        history_digest="history",
        response_digest="response",
        binding=CheckpointBinding(
            tenant_id="public",
            response_id=str(
                response.id if rejection == "content_free" else response.id + 1
            ),
        ),
        revision=1,
        progress={"private": "answer"},
        compaction_checkpoint=None,
        request_params=None,
        message_payloads=[],
        input_messages=[],
        input_payloads=[],
    )
    executed_sql.clear()
    expected_error = "Content-free" if rejection == "content_free" else "binding"
    with pytest.raises(ValueError, match=expected_error):
        publish_checkpoint__no_commit(
            db_session,
            response.id,
            checkpoint,
            expected_ownership_version=1 if existing_checkpoint else None,
        )
    db_session.flush()
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in executed_sql
    )
    assert response.response_status == RunStatus.RUNNING
    saved = db_session.get(ChatResponseCheckpoint, response.id)
    if existing_checkpoint:
        assert saved is not None
        assert saved.state == {}
        assert saved.ownership_version == 1
    else:
        assert saved is None


def test_agent_inbox_acceptance_preserves_content_and_source(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(db_session, parent, uuid4(), "First answer")
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None and child.agent_id is not None
    child_row.response_status = RunStatus.RUNNING
    branch = ChatBranch(chat_session_id=conversation.id, message_ids=[response.id])
    request = AgentMessageRequest(
        agent_id=child.agent_id,
        parent_id=str(conversation.id),
        message=UserMessage(content="Check the second source"),
        delivery=MessageDelivery.SEND,
        max_steps=3,
        total_timeout_s=30,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
    )
    receipt = enqueue_message(db_session, branch, request, response.id)
    [received] = read_run_inputs(db_session, child.agent_id, child.run_id, None, None)[
        0
    ]
    assert received.id == receipt.id
    assert isinstance(received.metadata, InputMessageMetadata)
    assert received.metadata.source_run_id == parent.run_id
    assert consume_inputs__no_commit(
        db_session,
        int(child.run_id),
        [received],
        branch.message_ids,
        ownership_version=None,
    )
    child.steps.append(
        StepRecord(
            input_messages=[received],
            message=AssistantMessage(id=f"{child.run_id}:1"),
            generation_status=ExecutionStatus.RUNNING,
        )
    )
    write_response_items(db_session, child_row, child, {})
    db_session.flush()
    assert pending_inputs(db_session, branch, child.agent_id) == []
    db_session.expire_all()
    [accepted] = read_response_steps(child_row)[-1].input_messages
    assert accepted.content == request.message.content
    assert accepted.id == receipt.id
    assert isinstance(accepted.metadata, InputMessageMetadata)
    assert accepted.metadata.source == InputSource.AGENT
    assert (
        db_session.scalar(select(ChatInput).where(ChatInput.message_id == receipt.id))
        is None
    )


def test_agent_message_over_the_byte_limit_is_not_stored(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(db_session, parent, uuid4(), "First answer")
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None and child.agent_id is not None
    child_row.response_status = RunStatus.RUNNING
    branch = ChatBranch(chat_session_id=conversation.id, message_ids=[response.id])
    # Two-byte characters: the text fits the limit in characters but not in bytes.
    content = "\u00e9" * (MAX_PENDING_MESSAGE_BYTES // 2 + 1)
    request = AgentMessageRequest(
        agent_id=child.agent_id,
        parent_id=str(conversation.id),
        message=UserMessage(content=content),
        delivery=MessageDelivery.SEND,
        max_steps=3,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
    )
    with pytest.raises(OnyxError) as error:
        enqueue_message(db_session, branch, request, response.id)
    assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert pending_inputs(db_session, branch, child.agent_id) == []


def test_unreceived_send_starts_the_next_child_run(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(db_session, parent, uuid4(), "First answer")
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None and child.agent_id is not None
    child_row.chat_session.restoration_config = ChatConfiguration(kind="chat")
    child_row.response_status = RunStatus.RUNNING
    branch = ChatBranch(chat_session_id=conversation.id, message_ids=[response.id])
    request = AgentMessageRequest(
        agent_id=child.agent_id,
        parent_id=str(conversation.id),
        message=UserMessage(content="Pending steering"),
        delivery=MessageDelivery.SEND,
        max_steps=3,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
    )
    late = enqueue_message(db_session, branch, request, response.id)
    assert late.run_id == child.run_id
    assert has_pending_sends(db_session, child.agent_id, int(child.run_id), None)
    child_row.response_status = RunStatus.ERROR
    idle = enqueue_message(db_session, branch, request, response.id)
    assert idle.run_id is None
    queued = enqueue_message(
        db_session,
        branch,
        request.model_copy(update={"delivery": MessageDelivery.QUEUE}),
        response.id,
    )

    def can_start(receipt_id: str) -> bool:
        row = by_id[receipt_id]
        return can_start_input(
            row.delivery, row.target_response_id, child_row.response_status
        )

    by_id = {
        row.message_id: row
        for row in pending_inputs(db_session, branch, child.agent_id)
    }
    # A send that its run never read waits like queued input after a failure.
    assert not can_start(late.id)
    assert can_start(idle.id)
    assert not can_start(queued.id)
    child_row.response_status = RunStatus.COMPLETE
    assert can_start(late.id) and can_start(queued.id)


def test_existing_descendant_accepts_an_ancestor_invocation_without_reparenting(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(db_session, parent, uuid4(), "Child answer")
    grandchild_id = uuid4()
    grandchild = _child_record(db_session, child, grandchild_id, "Grandchild answer")
    sibling = _child_record(db_session, parent, uuid4(), "Sibling answer")
    _save(db_session, response, parent)
    descendant_session = db_session.get(ChatSession, grandchild_id)
    assert descendant_session is not None
    original_creation_id = descendant_session.spawned_by_message_id
    later_response = _response(db_session, conversation, previous=response)
    later_parent = _record(later_response)
    followup = _child_record(
        db_session,
        later_parent,
        grandchild_id,
        "Direct followup",
        previous=grandchild.run_id,
        path=grandchild.agent_path,
    )
    _save(db_session, later_response, later_parent)
    assert descendant_session.spawned_by_message_id == original_creation_id
    stored = db_session.get(ChatMessage, int(followup.run_id))
    assert stored is not None and stored.parent_message is not None
    assert stored.parent_message.parent_message_id == int(grandchild.run_id)
    assert stored.parent_message.invoking_tool_call is not None
    assert (
        stored.parent_message.invoking_tool_call.parent_chat_message_id
        == later_response.id
    )
    db_session.commit()
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    def owner(response_id: int, visible: list[int]) -> ChatRunStore:
        return ChatRunStore(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            chat_session_id=conversation.id,
            response_id=response_id,
            visible_response_ids=visible,
            cache=cache,
            follow_up_steps=4,
            control_cache=cache,
        )

    later_owner = owner(later_response.id, [response.id])
    assert child.agent_id is not None and sibling.agent_id is not None
    assert (
        later_owner.read_run_status(followup.run_id, child.agent_id)
        == RunStatus.COMPLETE
    )
    with pytest.raises(ValueError, match="unavailable to this parent"):
        later_owner.read_run_status(followup.run_id, sibling.agent_id)
    with pytest.raises(ValueError, match="unavailable on this branch"):
        owner(response.id, []).read_run_status(followup.run_id, child.agent_id)


def test_unrestorable_agent_rejects_queue_and_start_failure_has_durable_result(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(db_session, parent, uuid4(), "Initial answer")
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None and child.agent_id is not None
    branch = ChatBranch(chat_session_id=conversation.id, message_ids=[response.id])
    request = AgentMessageRequest(
        agent_id=child.agent_id,
        parent_id=str(conversation.id),
        message=UserMessage(content="A new task"),
        delivery=MessageDelivery.QUEUE,
        max_steps=3,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
    )
    for delivery in (MessageDelivery.SEND, MessageDelivery.QUEUE):
        with pytest.raises(ValueError, match="cannot start another run"):
            enqueue_message(
                db_session,
                branch,
                request.model_copy(update={"delivery": delivery}),
                response.id,
            )
    assert pending_inputs(db_session, branch, child.agent_id) == []
    child_row.chat_session.restoration_config = ChatConfiguration(kind="chat")
    receipt = enqueue_message(db_session, branch, request, response.id)
    fail_inbox_start__no_commit(db_session, branch, child.agent_id, receipt.id)
    db_session.flush()
    assert pending_inputs(db_session, branch, child.agent_id) == []
    failed = latest_agent_response(db_session, branch, child.agent_id)
    assert failed is not None and failed.id != child_row.id
    assert failed.response_status == RunStatus.ERROR
    assert failed.response_failure is not None
    assert failed.parent_message is not None
    assert failed.parent_message.message == "A new task"
    assert failed.parent_message.parent_message_id == child_row.id
    # A second owner must not reserve another failed response for the same request.
    fail_inbox_start__no_commit(db_session, branch, child.agent_id, receipt.id)
    latest = latest_agent_response(db_session, branch, child.agent_id)
    assert latest is not None and latest.id == failed.id


@pytest.mark.parametrize("operation", ["accept", "save"])
def test_agent_input_submission_does_not_deadlock_response_updates(
    db_session: Session, conversation: ChatSession, operation: str
) -> None:
    response = _response(db_session, conversation)
    parent = _record(response)
    child = _child_record(db_session, parent, uuid4(), "First answer")
    _save(db_session, response, parent)
    child_row = db_session.get(ChatMessage, int(child.run_id))
    assert child_row is not None and child.agent_id is not None
    child_row.response_status = RunStatus.RUNNING
    response_id = child_row.id
    agent_id = child.agent_id
    branch = ChatBranch(chat_session_id=conversation.id, message_ids=[response.id])
    request = AgentMessageRequest(
        agent_id=agent_id,
        parent_id=str(conversation.id),
        message=UserMessage(content="Follow this instruction"),
        delivery=MessageDelivery.SEND,
        max_steps=3,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
    )
    db_session.commit()
    if operation == "save":
        check_checkpoint_owner__no_commit(db_session, response_id, None)
    else:
        lock_agent(db_session, agent_id)
    backend_pid: Queue[int] = Queue()

    def update_response() -> None:
        with Session(db_session.get_bind()) as session:
            pid = session.scalar(select(func.pg_backend_pid()))
            assert pid is not None
            backend_pid.put(pid)
            if operation == "accept":
                assert consume_inputs__no_commit(
                    session, response_id, [], [], ownership_version=None
                )
            else:
                enqueue_message(session, branch, request, branch.message_ids[0])
            session.commit()

    worker = start_thread_future(update_response, name="test-input-transaction")
    try:
        pid = backend_pid.get(timeout=10)
        pause = threading.Event()
        blocked = False
        for _ in range(500):
            blocked = bool(
                db_session.scalar(select(func.cardinality(func.pg_blocking_pids(pid))))
            )
            if blocked:
                break
            pause.wait(0.01)
        assert blocked, "Concurrent input operation did not reach its lock"
        if operation == "save":
            child.steps[0].message.content.append(
                ToolCall(id="search", name="search", arguments={})
            )
            write_response_items(db_session, child_row, child, {})
        else:
            enqueue_message(db_session, branch, request, response.id)
        db_session.commit()
        worker.result(timeout=10)
    finally:
        db_session.rollback()
        worker.result(timeout=10)


def test_agents_that_message_each_other_keep_their_turn(
    db_session: Session, conversation: ChatSession
) -> None:
    """Messages between agents chain more runs than the spawn depth allows."""
    response = _response(db_session, conversation)
    root = _record(response)
    first = _child_record(
        db_session, root, uuid4(), "first", path="/root/a", tool_name="spawn_agent"
    )
    second = _child_record(
        db_session, root, uuid4(), "second", path="/root/b", tool_name="spawn_agent"
    )
    for record in (first, second):
        save_response_record__no_commit(db_session, response.id, record)
    latest = {first.agent_id: first, second.agent_id: second}
    sender = second
    for hop in range(MAX_AGENT_DEPTH + 2):
        recipient = latest[
            first.agent_id if sender.agent_id == second.agent_id else second.agent_id
        ]
        reply = _child_record(
            db_session,
            sender,
            UUID(recipient.agent_id),
            f"hop {hop}",
            previous=recipient.run_id,
            path=recipient.agent_path,
            tool_name="send_message",
        )
        save_response_record__no_commit(db_session, response.id, reply)
        latest[reply.agent_id] = reply
        sender = reply
    last = db_session.get(ChatMessage, int(sender.run_id))
    assert last is not None
    assert root_response_id(db_session, last) == response.id
    status = read_response_status__no_commit(db_session, last.id)
    assert status is not None and status.root_message_id == response.id
    branch = ChatBranch(
        chat_session_id=conversation.id,
        message_ids=visible_message_ids(db_session, response),
    )
    selected = latest_agent_response(db_session, branch, sender.agent_id or "")
    assert selected is not None and selected.id == last.id


def test_a_later_turns_run_saves_under_an_earlier_turns_sender(
    db_session: Session, conversation: ChatSession
) -> None:
    """A message from an agent of an earlier turn continues a run of a later turn."""
    first_turn = _response(db_session, conversation)
    sender = _child_record(
        db_session,
        _record(first_turn),
        uuid4(),
        "sender",
        path="/root/sender",
        tool_name="spawn_agent",
    )
    later_turn = _response(db_session, conversation, "Later", previous=first_turn)
    recipient = _child_record(
        db_session,
        _record(later_turn),
        uuid4(),
        "recipient",
        path="/root/recipient",
        tool_name="spawn_agent",
    )
    save_response_record__no_commit(db_session, later_turn.id, recipient)
    sender.steps = _steps(
        sender.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="message", name="send_message", arguments={})]
            )
        ],
    )
    save_response_record__no_commit(db_session, first_turn.id, sender)
    run_id = reserve_child_response__no_commit(
        db_session,
        later_turn.id,
        agent=AgentInfo(
            id=recipient.agent_id or "",
            path=recipient.agent_path,
            parent_id=str(conversation.id),
            description="",
            restoration_config=None,
        ),
        instruction=UserMessage(content="Continue"),
        previous_response_id=int(recipient.run_id),
        parent_response_id=int(sender.run_id),
        parent_message_id=f"{sender.run_id}:0",
        parent_tool_call_id="message",
        delivers_result=True,
    )
    save_response_record__no_commit(
        db_session,
        later_turn.id,
        ResponseRecord(
            agent_id=recipient.agent_id,
            agent_path=recipient.agent_path,
            run_id=str(run_id),
            previous_run_id=recipient.run_id,
            parent_run_id=sender.run_id,
            parent_message_id=f"{sender.run_id}:0",
            parent_tool_call_id="message",
            status=RunStatus.RUNNING,
            input_messages=[
                UserMessage(id=f"run:{run_id}:input:0", content="Continue")
            ],
            steps=_steps(
                str(run_id), [AssistantMessage(content=[TextContent(text="Partial")])]
            ),
        ),
    )
    saved = db_session.get(ChatMessage, run_id)
    assert saved is not None
    assert [item.message.text for item in saved.response_items] == ["Partial"]


def test_a_run_whose_previous_run_is_off_the_branch_is_not_selected(
    db_session: Session, conversation: ChatSession
) -> None:
    """An earlier turn's agent can continue a later turn's agent; a sibling of
    the later turn sees neither run."""
    first_turn = _response(db_session, conversation)
    sender = _child_record(
        db_session,
        _record(first_turn),
        uuid4(),
        "sender",
        path="/root/sender",
        tool_name="spawn_agent",
    )
    later_turn = _response(db_session, conversation, "Later", previous=first_turn)
    recipient = _child_record(
        db_session,
        _record(later_turn),
        uuid4(),
        "recipient",
        path="/root/recipient",
        tool_name="spawn_agent",
    )
    save_response_record__no_commit(db_session, later_turn.id, recipient)
    sender.steps = _steps(
        sender.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="message", name="send_message", arguments={})]
            )
        ],
    )
    save_response_record__no_commit(db_session, first_turn.id, sender)
    run_id = reserve_child_response__no_commit(
        db_session,
        later_turn.id,
        agent=AgentInfo(
            id=recipient.agent_id or "",
            path=recipient.agent_path,
            parent_id=str(conversation.id),
            description="",
            restoration_config=None,
        ),
        instruction=UserMessage(content="Continue"),
        previous_response_id=int(recipient.run_id),
        parent_response_id=int(sender.run_id),
        parent_message_id=f"{sender.run_id}:0",
        parent_tool_call_id="message",
        delivers_result=True,
    )
    db_session.flush()
    agent_id = recipient.agent_id or ""
    later_branch = ChatBranch(
        chat_session_id=conversation.id, message_ids=[first_turn.id, later_turn.id]
    )
    latest = chat_subagents.latest_agent_response(db_session, later_branch, agent_id)
    assert latest is not None and latest.id == run_id

    sibling_branch = ChatBranch(
        chat_session_id=conversation.id, message_ids=[first_turn.id]
    )
    assert (
        chat_subagents.latest_agent_response(db_session, sibling_branch, agent_id)
        is None
    )


def test_a_run_that_continues_a_later_turn_belongs_to_that_turn(
    db_session: Session, conversation: ChatSession
) -> None:
    """An earlier turn's agent continues a later turn's agent; the new run, and
    any run after it, belongs to the later turn."""
    first_turn = _response(db_session, conversation)
    sender = _child_record(
        db_session,
        _record(first_turn),
        uuid4(),
        "sender",
        path="/root/sender",
        tool_name="spawn_agent",
    )
    later_turn = _response(db_session, conversation, "Later", previous=first_turn)
    recipient = _child_record(
        db_session,
        _record(later_turn),
        uuid4(),
        "recipient",
        path="/root/recipient",
        tool_name="spawn_agent",
    )
    save_response_record__no_commit(db_session, later_turn.id, recipient)
    sender.steps = _steps(
        sender.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="message", name="send_message", arguments={})]
            )
        ],
    )
    save_response_record__no_commit(db_session, first_turn.id, sender)
    run_id = reserve_child_response__no_commit(
        db_session,
        later_turn.id,
        agent=AgentInfo(
            id=recipient.agent_id or "",
            path=recipient.agent_path,
            parent_id=str(conversation.id),
            description="",
            restoration_config=None,
        ),
        instruction=UserMessage(content="Continue"),
        previous_response_id=int(recipient.run_id),
        parent_response_id=int(sender.run_id),
        parent_message_id=f"{sender.run_id}:0",
        parent_tool_call_id="message",
        delivers_result=True,
    )
    db_session.flush()
    continued = db_session.get(ChatMessage, run_id)
    assert continued is not None
    # The invocation traces to the first turn; the previous run to the later one.
    assert root_response_id(db_session, continued) == later_turn.id
    status = read_response_status__no_commit(db_session, run_id)
    assert status is not None and status.root_message_id == later_turn.id
    sender_row = db_session.get(ChatMessage, int(sender.run_id))
    assert sender_row is not None
    assert root_response_id(db_session, sender_row) == first_turn.id
