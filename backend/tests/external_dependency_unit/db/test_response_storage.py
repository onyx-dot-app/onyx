"""Response storage preserves accepted content, branch lineage, and compaction."""

from collections.abc import Generator
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, event, func, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.unitofwork import UOWTransaction

from ee.onyx.db.usage_export import get_empty_chat_messages_entries__paginated
from ee.onyx.server.reporting.usage_export_models import FlowType
from onyx.agents.models import (
    AgentInfo,
    CompactionCheckpoint,
    ExecutionStatus,
    RunFailure,
    RunFailureKind,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
    messages_from_steps,
)
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.presentation import project_response, replay_response
from onyx.chat.response_models import (
    ChatResponseSnapshot,
    MessageRendering,
    ResponseRecord,
)
from onyx.chat.save_chat import save_chat_turn as save_legacy_chat_turn
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SavedSearchDoc, SearchDoc, SearchDocsResponse
from onyx.db import chat_subagents
from onyx.db.chat import (
    checkpoint_from_summary,
    delete_chat_session,
    find_summary_for_ancestry,
    get_chat_message,
    get_or_create_root_message,
    load_message_branch,
    root_response_id,
    visible_message_ids,
)
from onyx.db.chat_response import (
    read_chat_execution,
    read_response_replay_data,
    read_response_steps,
    reserve_child_response__no_commit,
    save_chat_response_to_db,
    save_response_content,
    save_response_record__no_commit,
    write_response_items,
)
from onyx.db.chat_subagents import (
    ChatBranch,
    _load_history,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatResponseItem,
    ChatSession,
    Tool,
    User,
)
from onyx.db.models import SearchDoc as StoredSearchDoc
from onyx.db.models import ToolCall as StoredToolCall
from onyx.llm.models import (
    AssistantMessage,
    ImageContentPart,
    ImageUrlDetail,
    Message,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    MemoryToolDelta,
    SearchToolDocumentsDelta,
)
from onyx.tools.records import ToolCallInfo
from onyx.tools.results import (
    CodingAgentCallResult,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    FileReadResult,
    GeneratedImage,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryOperation,
    MemoryUpdated,
    ResearchAgentCallResult,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse


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
    response = ChatMessage(
        chat_session_id=conversation.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
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
) -> ResponseRecord:
    path = path or f"{parent.agent_path}/research"
    parent.steps = _steps(
        parent.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
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
    assert tool.tool_call_response == ""
    assert tool.result is not None
    assert tool.result.content == result.content
    assert tool.generated_images is None


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
    assert restored.messages[4].text == "Final answer"
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
    assert all(tool.tool_call_response == "" for tool in tools)
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
        agents = load_session_agent_metadata(
            selected.id, branch=branch, include_root=False
        )
        assert {agent.id for agent in agents} == expected
    assert (
        lookup_session_agent(base.id, str(grandchild_id), str(conversation.id)) is None
    )
    with pytest.raises(ValueError, match="unavailable"):
        lookup_session_agent(sibling.id, str(grandchild_id), str(child_id))

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
        assert lookup_session_agent(branch.id, str(grandchild_id), str(child_id))


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
        )
    assert db_session.get(ChatSession, child_id) is None


def test_compaction_saves_only_new_output_on_selected_ancestry(
    db_session: Session, conversation: ChatSession
) -> None:
    first = _response(db_session, conversation)
    record = _record(first)
    checkpoint = CompactionCheckpoint(
        summary="Summary",
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
    assert summaries[0].parent_message_id == first.id
    selected = find_summary_for_ancestry(
        db_session, conversation.id, visible_message_ids(db_session, continued)
    )
    assert checkpoint_from_summary(selected) == checkpoint
    alternate = _response(db_session, conversation)
    assert (
        find_summary_for_ancestry(
            db_session, conversation.id, visible_message_ids(db_session, alternate)
        )
        is None
    )


def test_truncation_without_summary_does_not_create_summary_message(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    record.checkpoint = CompactionCheckpoint(
        summary="",
        covered_through_message_id=f"chat:{response.parent_message_id}",
    )
    _save(db_session, response, record)
    assert (
        find_summary_for_ancestry(
            db_session, conversation.id, visible_message_ids(db_session, response)
        )
        is None
    )


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
    ) == (1 if reuse_branch and not child_count else 2)
    assert sum(
        "WITH RECURSIVE session_ancestors" in query for query in executed_sql
    ) == bool(child_count)
    assert not any("chat_response_item" in query for query in executed_sql)


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


def test_legacy_writer_keeps_tool_results_and_display_text(
    db_session: Session, conversation: ChatSession, tool_record: Tool
) -> None:
    response = _response(db_session, conversation)
    save_legacy_chat_turn(
        message_text="Existing answer",
        reasoning_tokens="Existing thinking",
        tool_calls=[
            ToolCallInfo(
                parent_tool_call_id=None,
                turn_index=0,
                tab_index=0,
                tool_name="lookup",
                tool_call_id="legacy-call",
                tool_id=tool_record.id,
                reasoning_tokens="Tool thinking",
                tool_call_arguments={"query": "cedar"},
                tool_call_response="Existing result",
            )
        ],
        citation_to_doc={},
        all_search_docs={},
        db_session=db_session,
        assistant_message=response,
    )
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
            select(StoredToolCall.tool_call_response).where(
                StoredToolCall.id == tool.id
            )
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
    reference = execution.tool_records[0]
    assert (
        replay.tools[(reference.message_id, reference.tool_call_id)].tool_id
        == tool_record.id
    )
    invalid = execution.model_copy(deep=True)
    invalid.tool_records[0].message_id = "unrelated-message"
    with pytest.raises(ValueError, match="not part of this response"):
        read_response_replay_data(invalid, db_session)


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


def test_legacy_save_preserves_distinct_document_version_keys(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    documents = [
        SearchDoc(
            document_id="same-document",
            chunk_ind=index,
            semantic_identifier="Guide",
            blurb=f"Part {index}",
            source_type=DocumentSource.WEB,
            boost=1,
            hidden=False,
            metadata={},
            match_highlights=[f"<hi>{index}</hi>"],
        )
        for index in range(2)
    ]
    save_legacy_chat_turn(
        message_text="Answer",
        reasoning_tokens=None,
        tool_calls=[],
        citation_to_doc={},
        all_search_docs={
            ChatStateContainer.create_search_doc_key(doc, use_simple_key=False): doc
            for doc in documents
        },
        db_session=db_session,
        assistant_message=response,
    )
    db_session.expire_all()
    assert {
        (doc.chunk_ind, tuple(doc.match_highlights or []))
        for doc in response.search_docs or []
    } == {(doc.chunk_ind, tuple(doc.match_highlights)) for doc in documents}


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
