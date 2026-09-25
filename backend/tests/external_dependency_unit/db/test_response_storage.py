"""Response storage preserves accepted content, branch lineage, and compaction."""

import threading
from collections.abc import Generator
from contextlib import nullcontext
from queue import Queue
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, inspect, select
from sqlalchemy.orm import Session

from onyx.agents.compaction import history_digest
from onyx.agents.events import ToolEndEvent, ToolStartEvent, ToolUpdateEvent
from onyx.agents.execution_records import (
    CompactionCheckpoint,
    ExecutionStatus,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.agents.models import (
    RunState,
    StepRecord,
    ToolExecutionRecord,
    messages_from_steps,
)
from onyx.agents.tools import ToolProgress
from onyx.chat.emitter import Emitter
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.models import ChatResponseSnapshot, MessageRendering, ResponseRecord
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.configs.constants import MessageType
from onyx.db import chat_subagents
from onyx.db.chat import (
    delete_chat_session,
    delete_messages_and_files_from_chat_session,
    get_chat_message,
    get_or_create_root_message,
    reserve_chat_response_ids,
)
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    read_response__no_commit,
    save_response_record__no_commit,
)
from onyx.db.chat_history import (
    capture_chat_history,
    checkpoint_from_summary,
    convert_chat_history,
    find_summary_for_ancestry,
    load_message_branch,
)
from onyx.db.chat_response import (
    read_chat_execution,
    save_chat_response_to_db,
    save_response_content,
)
from onyx.db.chat_response_messages import (
    read_response_steps,
    write_response_messages,
)
from onyx.db.chat_subagents import (
    ChatBranch,
    _load_history,
    load_session_agent_metadata,
    lookup_session_agent,
    visible_message_ids,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatResponseMessage, ChatSession, Tool
from onyx.db.models import ToolCall as StoredToolCall
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.llm.models import (
    AssistantMessage,
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
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    ItemUpdate,
    Packet,
    ToolItem,
)
from onyx.tools.models import LlmPythonExecutionResult
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.utils.threadpool_concurrency import start_thread_future


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
    yield session
    db_session.rollback()
    db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
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
    run_id = str(uuid4())
    return ResponseRecord(
        agent_id=str(response.chat_session_id),
        run_id=run_id,
        status=RunStatus.COMPLETE,
        input_messages=[UserMessage(content=response.parent_message.message)],
        steps=_steps(run_id, [AssistantMessage(content=[TextContent(text=answer)])]),
        answer_step_index=0,
    )


def _save(db_session: Session, response: ChatMessage, record: ResponseRecord) -> None:
    save_response_content(response, record, db_session=db_session, persist_content=True)
    db_session.flush()
    db_session.expire(response)


def _child_record(
    parent: ResponseRecord,
    child_id: UUID,
    answer: str,
    previous: str | None = None,
) -> ResponseRecord:
    parent.steps = _steps(
        parent.run_id,
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            )
        ],
    )

    run_id = str(uuid4())
    child = ResponseRecord(
        agent_id=str(child_id),
        agent_path="/root/research",
        run_id=run_id,
        previous_run_id=previous,
        parent_run_id=parent.run_id,
        parent_message_id=f"{parent.run_id}:0",
        parent_tool_call_id="delegate",
        status=RunStatus.COMPLETE,
        input_messages=[UserMessage(content=f"Find {answer}")],
        steps=_steps(run_id, [AssistantMessage(content=[TextContent(text=answer)])]),
        answer_step_index=0,
    )
    parent.child_runs.append(child)
    return child


def test_response_tools_flush_together_and_keep_result_links(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    calls = [ToolCall(id=f"call-{i}", name="search", arguments={}) for i in range(4)]
    messages: list[Message] = [AssistantMessage(content=list(calls))]
    messages.extend(
        ToolResultMessage(tool_call_id=call.id, tool_name=call.name, content=call.id)
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
            tools = write_response_messages(
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
        assert read_response_steps(response) == steps
        for call in calls:
            linked = [
                row.tool_call_id
                for row in response.response_messages
                if row.tool_call is not None and row.tool_call.tool_call_id == call.id
            ]
            assert len(linked) == 1


def test_resumed_tool_results_keep_row_identity_and_model_call_order(
    db_session: Session, conversation: ChatSession
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
                    tool_call_id="second", tool_name="search", content="Second result"
                ),
            ),
        },
    )
    record.steps = [step]
    save_response_record__no_commit(db_session, response.id, record)
    db_session.flush()
    db_session.expire(response)
    second_row = response.response_messages[1]
    second_id, second_position = second_row.id, second_row.position
    suspended = read_chat_execution(response)
    assert suspended is not None and suspended.response is not None
    assert suspended.response.steps == record.steps
    assert suspended.response.steps[0].tools["first"].result is None

    step.tools["first"] = ToolExecutionRecord(
        status=ExecutionStatus.COMPLETE,
        result=ToolResultMessage(
            tool_call_id="first", tool_name="search", content="First result"
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
    assert restored.response.steps == record.steps
    assert [message.text for message in restored.response.messages] == [
        "",
        "First result",
        "Second result",
        "Answer",
    ]
    stored_second = next(
        row for row in response.response_messages if row.id == second_id
    )
    assert stored_second.position == second_position
    assert restored.response.answer_step_index == 1


def test_response_messages_preserve_order_provider_metadata_and_tool_identity(
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
            tool_call_id="same-id", tool_name="search", content="First result"
        ),
        AssistantMessage(
            content=[
                TextContent(text="Checking again."),
                ToolCall(id="same-id", name="search", arguments={"query": "second"}),
            ]
        ),
        ToolResultMessage(
            tool_call_id="same-id", tool_name="search", content="Second result"
        ),
        AssistantMessage(content=[TextContent(text="Final answer")]),
    ]
    answer_index = 2

    record.steps = _steps(record.run_id, messages, ExecutionStatus(record.status.value))

    record.answer_step_index = answer_index
    _save(db_session, response, record)
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
    assert all(tool.legacy_response == "" for tool in tools)
    result_ids = [
        row.tool_call_id
        for row in response.response_messages
        if row.tool_call_id is not None
    ]
    assert set(result_ids) == {tool.id for tool in tools}
    assert len(result_ids) == 2


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
    saved_settings = response.response_messages[0].rendering
    assert saved_settings is not None
    assert "run_id" not in saved_settings and "step_index" not in saved_settings


def test_partial_tool_arguments_survive_storage_without_executable_arguments(
    db_session: Session, conversation: ChatSession
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
                    raw_arguments='{"query": "half',
                    arguments_complete=False,
                )
            ]
        )
    ]
    record.steps = _steps(record.run_id, messages, ExecutionStatus(record.status.value))

    _save(db_session, response, record)
    assistant = read_response_steps(response)[0].message
    assert isinstance(assistant, AssistantMessage)
    calls = assistant.tool_calls
    assert len(calls) == 1
    assert calls[0].raw_arguments == '{"query": "half'
    assert calls[0].arguments_complete is False
    assert calls[0].arguments == {}


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
            .select_from(ChatResponseMessage)
            .where(ChatResponseMessage.chat_message_id == response.id)
        )
        == 0
    )


def test_old_rows_keep_the_legacy_reader(
    db_session: Session, conversation: ChatSession
) -> None:
    response = _response(db_session, conversation)
    response.message = "Existing answer"
    assert (
        execution.response if (execution := read_chat_execution(response)) else None
    ) is None
    history = convert_chat_history(
        chat_history=capture_chat_history([response], {}, len),
        files=[],
        context_image_files=[],
        additional_context=None,
        token_counter=len,
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
    _child_record(parent, child_id, "Base")
    _save(db_session, base, parent)
    base_execution = read_chat_execution(base)
    assert base_execution is not None
    previous = base_execution.response.child_runs[0].run_id
    branches = [_response(db_session, conversation, previous=base) for _ in range(2)]
    for index in [1, 0] if reverse_save_order else [0, 1]:
        parent = _record(branches[index])
        _child_record(parent, child_id, f"Branch {index}", previous)
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
    child_record = _child_record(parent, child_id, "Child")
    grandchild_record = _child_record(child_record, grandchild_id, "Base")
    grandchild_record.agent_path = "/root/research/facts"
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
    assert (
        lookup_session_agent(base.id, str(grandchild_id), str(conversation.id)) is None
    )
    with pytest.raises(ValueError, match="unavailable"):
        lookup_session_agent(sibling.id, str(grandchild_id), str(child_id))

    branches = [_response(db_session, conversation, previous=base) for _ in range(2)]
    for index in [1, 0] if reverse_save_order else [0, 1]:
        parent = _record(branches[index])
        child_record = _child_record(parent, child_id, "Child", child_saved.run_id)
        grandchild_record = _child_record(
            child_record, grandchild_id, f"Branch {index}", grandchild_saved.run_id
        )
        grandchild_record.agent_path = "/root/research/facts"
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
    first = _child_record(parent, child_id, "First")
    _child_record(parent, child_id, "Second", first.run_id)
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
    _child_record(parent, child_id, "First")
    _child_record(parent, child_id, "Unrelated")
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
    _child_record(parent, child_id, "Answer")
    transaction = db_session.begin_nested()
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
    child = _child_record(parent, child_id, "Answer")
    child.input_messages = [
        UserMessage(
            content=[
                ImageContentPart(
                    image_url=ImageUrlDetail(url="https://example.com/image.png")
                )
            ]
        )
    ]
    with pytest.raises(ValueError, match="text only"):
        save_response_content(
            response, parent, db_session=db_session, persist_content=True
        )
    assert db_session.get(ChatSession, child_id) is None


def test_compaction_saves_only_new_output_on_selected_ancestry(
    db_session: Session, conversation: ChatSession
) -> None:
    first = _response(db_session, conversation)
    record = _record(first)
    checkpoint = CompactionCheckpoint(
        summary="Summary",
        covered_count=1,
        covered_digest=history_digest(record.input_messages),
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
                ChatMessage.summary_covered_count.is_not(None),
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


@pytest.mark.parametrize("tool_kind", ["python", "coding"])
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
            generated_files=[],
        )
        result = ToolResult(content=output.model_dump_json(), details=output)
        progress = ToolProgress(
            details=output.model_copy(update={"stdout": "hello ", "stderr": ""})
        )
        implementation = PythonTool.__name__
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
    agent_id, run_id = str(session.id), str(uuid4())
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
    presenter = ResponsePresenter(Emitter(queue.put_nowait, response_id=row.id))
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
    projected = project_response(
        snapshot, response_id=row.id, tool_ids={call.name: tool.id}
    )
    get_chat_history_store(
        message_id=row.id, chat_session_id=conversation.id, persist_content=True
    ).save_response(projected)
    db_session.refresh(row, ["response_messages", "search_docs"])
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(StoredToolCall)
            .where(StoredToolCall.parent_chat_message_id == row.id)
        )
        == 1
    )
    saved = translate_assistant_message_to_packets(row, db_session)
    live_items = [
        packet.obj.item
        for packet in live
        if isinstance(packet.obj, ItemUpdate) and isinstance(packet.obj.item, ToolItem)
    ]
    saved_items = [
        packet.obj.item
        for packet in saved
        if isinstance(packet.obj, ItemUpdate) and isinstance(packet.obj.item, ToolItem)
    ]
    assert live_items[-1].metadata == saved_items[-1].metadata == result.details
    assert live_items[-1].output == saved_items[-1].output


def test_exact_summary_keeps_legacy_baseline_selectable(
    db_session: Session, conversation: ChatSession
) -> None:
    base = _response(db_session, conversation)
    legacy = ChatMessage(
        chat_session_id=conversation.id,
        parent_message_id=base.id,
        last_summarized_message_id=base.parent_message_id,
        message="Legacy summary",
        message_type=MessageType.SUMMARY,
        token_count=2,
    )
    db_session.add(legacy)
    db_session.flush()
    response = _response(db_session, conversation, previous=base)
    record = _record(response)
    record.checkpoint = CompactionCheckpoint(
        summary="Exact summary",
        covered_count=1,
        covered_digest=history_digest(record.input_messages),
    )
    _save(db_session, response, record)
    ancestry = visible_message_ids(db_session, response)
    exact = find_summary_for_ancestry(db_session, conversation.id, ancestry)
    assert checkpoint_from_summary(exact) == record.checkpoint
    baseline = find_summary_for_ancestry(
        db_session, conversation.id, ancestry, legacy_only=True
    )
    assert baseline is not None and baseline.id == legacy.id


def test_session_delete_removes_reused_child_history_and_tool_items(
    db_session: Session, conversation: ChatSession
) -> None:
    base = _response(db_session, conversation)
    record = _record(base)
    child_id = uuid4()
    child = _child_record(record, child_id, "First")
    grandchild_id = uuid4()
    _child_record(child, grandchild_id, "Nested")
    _save(db_session, base, record)
    first = read_chat_execution(base)
    assert first is not None
    next_response = _response(db_session, conversation, previous=base)
    record = _record(next_response)
    _child_record(record, child_id, "Second", first.response.child_runs[0].run_id)
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
            .select_from(ChatResponseMessage)
            .where(ChatResponseMessage.chat_message_id.in_(response_ids))
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
        child = _child_record(record, uuid4(), "Partial child output")
        child.status = status
        record.child_runs = [child]
    else:
        record.status = status
    with pytest.raises(ValueError, match="terminal execution records"):
        _save(db_session, response, record)
    assert response.response_status is None
    assert response.response_messages == []


@pytest.mark.parametrize("child_count", [1, 4])
def test_discovery_batches_response_metadata(
    db_session: Session,
    conversation: ChatSession,
    executed_sql: list[str],
    monkeypatch: pytest.MonkeyPatch,
    child_count: int,
) -> None:
    monkeypatch.setattr(
        "onyx.db.chat_subagents.get_session_with_current_tenant",
        lambda: nullcontext(db_session),
    )
    response = _response(db_session, conversation)
    record = _record(response)
    for index in range(child_count):
        child = _child_record(record, uuid4(), f"Answer {index}")
        child.agent_path = f"/root/research_{index}"
    _save(db_session, response, record)
    message_id = response.id
    db_session.expire_all()
    executed_sql.clear()

    metadata = load_session_agent_metadata(message_id)

    assert len(metadata) == child_count + 1
    assert all(agent.latest_run_id is not None for agent in metadata)
    assert (
        sum("WITH RECURSIVE selected_responses" in query for query in executed_sql) == 2
    )
    assert not any("chat_response_message" in query for query in executed_sql)


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
            child = _child_record(record, uuid4(), f"Answer {index}")
            child.agent_path = f"/root/research_{index}"
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
    child = _child_record(record, uuid4(), "Child")
    grandchild = _child_record(child, uuid4(), "Grandchild")
    grandchild.agent_path = "/root/research/facts"
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
        sum("WITH RECURSIVE session_ancestors" in query for query in executed_sql) == 1
    )


def test_public_message_read_does_not_fetch_response_messages(
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
    assert not any("chat_response_message" in query for query in executed_sql)


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
    assert selected.response_messages
    assert "response_messages" in inspect(sibling).unloaded
    assert "response_messages" in inspect(later).unloaded
    assert "tool_calls" in inspect(sibling).unloaded
    assert "tool_calls" in inspect(later).unloaded
    assert sum("FROM chat_response_message" in query for query in executed_sql) == 1


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
            tool_call_id="search", tool_name="search", content=original_text
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
    assert record == original


@pytest.mark.parametrize(
    "save_order", ["lifecycle_first", "display_first", "concurrent"]
)
def test_lifecycle_and_display_saves_share_response_content(
    db_session: Session, conversation: ChatSession, save_order: str
) -> None:
    response = _response(db_session, conversation)
    record = _record(response)
    child_id = uuid4()
    child = _child_record(record, child_id, "Child answer")
    child.checkpoint = CompactionCheckpoint(
        summary="Child summary", covered_count=1, covered_digest="child-history"
    )
    root_id = response.id
    root_session_id = conversation.id
    initial = record.model_copy(
        update={
            "steps": [],
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
            cancelled=False,
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
        assert saved_root.message == "Answer"
        assert read_response_steps(saved_root) == record.steps
        saved_child = read_response__no_commit(db_session, child.run_id)
        assert saved_child is not None
        assert saved_child.response.parent_run_id == record.run_id
        assert saved_child.response.checkpoint == child.checkpoint
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
    assert not row.response_messages
