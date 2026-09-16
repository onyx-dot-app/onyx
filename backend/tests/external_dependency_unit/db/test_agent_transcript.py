"""Canonical output survives database storage and legacy display projection."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, Table, delete, inspect, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from onyx.agents.coordination import AgentInfo
from onyx.agents.models import RunSnapshot
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.transcript import (
    AgentConfiguration,
    AgentTranscript,
    OperationSnapshot,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.incognito_context import (
    append_incognito_message,
    get_or_create_incognito_root_id,
    teardown_incognito_session,
)
from onyx.chat.models import ChatResponseSnapshot, MessagePresentation, PresentationMode
from onyx.chat.presentation import project_response
from onyx.configs.constants import MessageType
from onyx.db.agent_transcript import (
    get_or_create_root_agent,
    load_agent_history,
    read_chat_execution,
    read_root_transcript,
    set_agent_transcript,
)
from onyx.db.chat import reserve_chat_response_ids
from onyx.db.chat_history import capture_chat_history, convert_chat_history
from onyx.db.chat_response import save_chat_response, save_chat_turn
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import AgentRun, ChatMessage, ChatSession, ChatSessionAgent, Tool
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import IntermediateReportDelta
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def _seed_agent(
    db_session: Session,
    *,
    chat_session_id: UUID,
    creation_message_id: int,
    agent_id: str,
    parent_agent_id: str | None,
    name: str,
    description: str,
    configuration: AgentConfiguration | None,
) -> None:
    db_session.add(
        ChatSessionAgent(
            id=agent_id,
            chat_session_id=chat_session_id,
            creation_message_id=creation_message_id if parent_agent_id else None,
            parent_agent_id=parent_agent_id,
            name=name,
            description=description,
            restoration_config=configuration.model_dump(mode="json")
            if configuration
            else {},
        )
    )
    db_session.flush()


@pytest.mark.parametrize("persist_content", [True, False])
def test_transcript_round_trip_and_content_free_policy(
    db_session: Session, persist_content: bool
) -> None:
    session = ChatSession(id=uuid4(), description="transcript test")
    db_session.add(session)
    db_session.flush()
    row = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(row)
    db_session.flush()
    root_id = str(uuid4())
    transcript = AgentTranscript(
        status="complete",
        run_id=str(uuid4()),
        agent_id=root_id,
        messages=[
            AssistantMessage(
                content=[
                    ThinkingContent(
                        text="reasoning",
                        blocks=[
                            ThinkingBlock(
                                thinking="reasoning", signature="signed-content"
                            )
                        ],
                    ),
                    TextContent(text="Checking."),
                    ToolCall(id="call", name="lookup", arguments={"query": "test"}),
                ]
            ),
            ToolResultMessage(
                tool_call_id="call", tool_name="lookup", content="full tool output"
            ),
            AssistantMessage(content=[TextContent(text="Raw answer [1].")]),
        ],
    )
    _seed_agent(
        db_session,
        chat_session_id=session.id,
        creation_message_id=row.id,
        agent_id=root_id,
        parent_agent_id=None,
        name="root",
        description="",
        configuration=None,
    )
    try:
        save_chat_turn(
            message_text="Displayed answer with a link.",
            reasoning_tokens="display reasoning",
            tool_calls=[],
            citation_to_doc={},
            all_search_docs={},
            db_session=db_session,
            assistant_message=row,
            agent_transcript=transcript,
            persist_content=persist_content,
        )
        db_session.expire(row)
        db_session.refresh(row, ["agent_runs"])
        stored = read_root_transcript(row)
        if persist_content:
            assert stored is not None
            assert row.response_rendering is not None
            assert "root_run_id" not in row.response_rendering
            assert stored.messages == transcript.messages
            history = convert_chat_history(
                chat_history=capture_chat_history([row], {}, len),
                files=[],
                context_image_files=[],
                additional_context=None,
                token_counter=len,
            ).messages
            assert history == transcript.messages
            assert history[-1].text == "Raw answer [1]."
        else:
            assert stored is None
            assert row.message == ""
            assert row.reasoning_tokens is None
    finally:
        db_session.delete(row)
        db_session.delete(session)
        db_session.commit()


def test_old_rows_keep_the_legacy_reader(db_session: Session) -> None:
    session = ChatSession(id=uuid4(), description="legacy transcript test")
    db_session.add(session)
    db_session.flush()
    row = ChatMessage(
        chat_session_id=session.id,
        message="Existing answer",
        token_count=2,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(row)
    db_session.flush()
    try:
        assert read_root_transcript(row) is None
        history = convert_chat_history(
            chat_history=capture_chat_history([row], {}, len),
            files=[],
            context_image_files=[],
            additional_context=None,
            token_counter=len,
        ).messages
        assert [item.text for item in history] == ["Existing answer"]
    finally:
        db_session.rollback()


def test_response_reservation_preserves_model_order_and_active_branch(
    db_session: Session,
) -> None:
    names = ["first", "second"]
    session = ChatSession(id=uuid4(), description="response reservation")
    db_session.add(session)
    db_session.flush()
    parent = ChatMessage(
        chat_session_id=session.id,
        message="hello",
        token_count=1,
        message_type=MessageType.USER,
    )
    db_session.add(parent)
    db_session.flush()
    ids: list[int] = []
    try:
        ids = reserve_chat_response_ids(db_session, session.id, parent.id, names)
        responses = [db_session.get(ChatMessage, message_id) for message_id in ids]
        assert [
            response.model_display_name for response in responses if response
        ] == names
        assert all(
            response and response.parent_message_id == parent.id
            for response in responses
        )
        db_session.refresh(parent)
        assert parent.latest_child_message_id == ids[-1]
    finally:
        parent.latest_child_message_id = None
        db_session.flush()
        for message_id in ids:
            response = db_session.get(ChatMessage, message_id)
            if response is not None:
                db_session.delete(response)
        db_session.flush()
        db_session.delete(parent)
        db_session.delete(session)
        db_session.commit()


def test_transcript_migration_is_reversible(db_session: Session) -> None:
    schema = f"transcript_migration_{uuid4().hex}"
    connection = db_session.connection()
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(
            text("SELECT set_config('search_path', :schema, true)"), {"schema": schema}
        )
        metadata = MetaData()
        Table(
            "chat_session",
            metadata,
            Column("id", PGUUID(as_uuid=True), primary_key=True),
        )
        Table("chat_message", metadata, Column("id", Integer, primary_key=True))
        metadata.create_all(connection)
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
        revision = scripts.get_revision("7a03b6e90c12")
        assert revision is not None
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
            assert {"chat_session_agent", "agent_run"} <= set(
                inspect(connection).get_table_names(schema=schema)
            )
            assert "response_rendering" in {
                column["name"]
                for column in inspect(connection).get_columns(
                    "chat_message", schema=schema
                )
            }
            revision.module.downgrade()
            assert set(inspect(connection).get_table_names(schema=schema)) == {
                "chat_session",
                "chat_message",
            }
            assert [
                column["name"]
                for column in inspect(connection).get_columns(
                    "chat_message", schema=schema
                )
            ] == ["id"]
            revision.module.upgrade()
            assert {"chat_session_agent", "agent_run"} <= set(
                inspect(connection).get_table_names(schema=schema)
            )
    finally:
        db_session.rollback()


@pytest.mark.parametrize(
    "failed,persist_content", [(False, True), (True, True), (True, False)]
)
def test_saved_execution_keeps_reused_call_ids_and_child_runs_distinct(
    db_session: Session,
    failed: bool,
    persist_content: bool,
) -> None:

    session = ChatSession(
        id=uuid4(),
        description="identified execution",
        incognito_record_mode=None
        if persist_content
        else IncognitoRecordMode.USAGE_ONLY,
    )
    parent_tool = Tool(name="delegate", description="Delegate work")
    leaf_tool = Tool(name="lookup", description="Read a value")
    db_session.add_all([session, parent_tool, leaf_tool])
    db_session.flush()
    row = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(row)
    db_session.flush()

    def child(run_id: str) -> RunSnapshot:
        return RunSnapshot(
            run_id=run_id,
            agent_id="reused-child",
            previous_run_id="left" if run_id == "right" else None,
            input_messages=[UserMessage(content=f"Task {run_id}")],
            parent_run_id="root",
            parent_message_id="root:0",
            parent_tool_call_id="reused",
            status=RunStatus.COMPLETE,
            messages=[
                AssistantMessage(
                    content=[ToolCall(id="reused", name="lookup", arguments={})]
                ),
                ToolResultMessage(
                    tool_call_id="reused", tool_name="lookup", content=run_id
                ),
                AssistantMessage(content=[TextContent(text=f"Report {run_id}")]),
            ],
            operations=[
                OperationSnapshot(
                    step_index=0, message_index=0, status=RunStatus.COMPLETE
                ),
                OperationSnapshot(
                    step_index=0,
                    message_index=0,
                    tool_call_id="reused",
                    status=RunStatus.COMPLETE,
                ),
                OperationSnapshot(
                    step_index=1, message_index=2, status=RunStatus.COMPLETE
                ),
            ],
        )

    root_id = str(uuid4())
    snapshot = RunSnapshot(
        run_id="root",
        agent_id=root_id,
        input_messages=[UserMessage(content="Root question")],
        status=RunStatus.ERROR if failed else RunStatus.COMPLETE,
        child_runs=[child("left"), child("right")],
        messages=[
            AssistantMessage(
                content=[ToolCall(id="reused", name="delegate", arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="reused", tool_name="delegate", content="First result"
            ),
            AssistantMessage(
                content=[ToolCall(id="reused", name="delegate", arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="reused", tool_name="delegate", content="Second result"
            ),
            AssistantMessage(content=[TextContent(text="Answer")]),
        ],
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.COMPLETE),
            OperationSnapshot(
                step_index=0,
                message_index=0,
                tool_call_id="reused",
                status=RunStatus.COMPLETE,
            ),
            OperationSnapshot(step_index=1, message_index=2, status=RunStatus.COMPLETE),
            OperationSnapshot(
                step_index=1,
                message_index=2,
                tool_call_id="reused",
                status=RunStatus.COMPLETE,
            ),
            OperationSnapshot(step_index=2, message_index=4, status=RunStatus.COMPLETE),
        ],
    )
    artifacts = project_tool_artifacts(
        snapshot, {"delegate": parent_tool.id, "lookup": leaf_tool.id}
    )
    projected = project_response(
        snapshot,
        response_id=row.id,
        tool_ids={"delegate": parent_tool.id, "lookup": leaf_tool.id},
        registrations=[
            AgentInfo(
                id="reused-child",
                path="/root/research",
                parent_id=root_id,
                description="",
                restoration_config=None,
            )
        ],
    )
    _seed_agent(
        db_session,
        chat_session_id=session.id,
        creation_message_id=row.id,
        agent_id=root_id,
        parent_agent_id=None,
        name="root",
        description="",
        configuration=None,
    )
    _seed_agent(
        db_session,
        chat_session_id=session.id,
        creation_message_id=row.id,
        agent_id="reused-child",
        parent_agent_id=root_id,
        name="research",
        description="",
        configuration=None,
    )
    db_session.commit()
    if not persist_content:
        append_incognito_message(session.id, UserMessage(content="Root question"))
        get_or_create_incognito_root_id(session.id, root_id)
    try:
        save_chat_response(
            message_id=row.id,
            response=ChatResponseSnapshot(
                error="Provider failed after tool acceptance" if failed else None,
                answer="Answer",
                reasoning=None,
                request_params=None,
                tool_calls=artifacts.tool_calls,
                citation_to_doc={},
                all_search_docs={},
                is_clarification=False,
                pre_answer_processing_time=None,
                transcript=projected.transcript,
                presentation=[
                    MessagePresentation(
                        run_id=run_id, step_index=1, mode=PresentationMode.REPORT
                    )
                    for run_id in ("left", "right")
                ],
                cancelled=False,
            ),
        )
        db_session.expire(row)
        if not persist_content:
            assert row.message == ""
            assert row.error == "The model encountered an error."
            assert row.response_rendering is None
            assert not row.tool_calls
            assert not row.search_docs
            assert row.token_count > 0
            return
        assert row.message == "Answer"
        assert row.error == (
            "Provider failed after tool acceptance" if failed else None
        )
        db_session.refresh(row, ["agent_runs"])
        record = read_chat_execution(row)
        assert record is not None
        assert len(record.tool_records) == 4
        assert len({reference.record_id for reference in record.tool_records}) == 4
        assert {
            (reference.message_id, reference.tool_call_id)
            for reference in record.tool_records
        } == {
            ("root:0", "reused"),
            ("root:1", "reused"),
            ("left:0", "reused"),
            ("right:0", "reused"),
        }
        packets = translate_assistant_message_to_packets(row, db_session)
        reports = [
            packet
            for packet in packets
            if isinstance(packet.obj, IntermediateReportDelta)
        ]
        assert len(reports) == 2
        assert {
            packet.identity.run_id for packet in reports if packet.identity is not None
        } == {"left", "right"}
        assert all(
            packet.identity is not None
            and packet.identity.parent_message_id == "root:0"
            and packet.identity.parent_tool_call_id == "reused"
            for packet in reports
        )
        db_session.refresh(row, ["agent_runs"])
        stored_record = read_chat_execution(row)
        assert stored_record is not None
        stored_transcript = stored_record.transcript
        assert stored_transcript is not None
        assert stored_transcript.input_messages == []
        assert [child.agent_id for child in stored_transcript.child_runs] == [
            "reused-child",
            "reused-child",
        ]
        assert [child.run_id for child in stored_transcript.child_runs] == [
            "left",
            "right",
        ]
        assert [
            child.input_messages[0].text for child in stored_transcript.child_runs
        ] == ["Task left", "Task right"]
        expected = snapshot.transcript()
        expected.input_messages.clear()
        assert stored_transcript.messages == expected.messages
    finally:
        if not persist_content:
            teardown_incognito_session(session.id)
        db_session.delete(row)
        db_session.delete(session)
        db_session.delete(parent_tool)
        db_session.delete(leaf_tool)
        db_session.commit()


@pytest.mark.parametrize("answer", [None, "Partial answer"])
def test_execution_error_is_saved_from_response_snapshot(
    db_session: Session,
    answer: str | None,
) -> None:
    session = ChatSession(id=uuid4(), description="failed response")
    db_session.add(session)
    db_session.flush()
    row = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(row)
    db_session.commit()
    response = ChatResponseSnapshot(
        answer=answer,
        reasoning=None,
        request_params=None,
        citation_to_doc={},
        tool_calls=[],
        is_clarification=False,
        all_search_docs={},
        pre_answer_processing_time=None,
        transcript=None,
        cancelled=False,
        error="Generation failed",
    )
    try:
        save_chat_response(message_id=row.id, response=response)
        db_session.refresh(row)
        assert row.error == response.error
        assert row.message == (answer or "")
    finally:
        db_session.delete(row)
        db_session.delete(session)
        db_session.commit()


def test_failed_run_stores_safe_failure_classification(db_session: Session) -> None:
    session = ChatSession(id=uuid4(), description="safe saved failure")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(message)
    db_session.flush()
    sensitive_detail = "synthetic-private-provider-credential"

    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise TimeoutError(sensitive_detail)

    agent = Agent(FakeModelClient(fail))
    _seed_agent(
        db_session,
        chat_session_id=session.id,
        creation_message_id=message.id,
        agent_id=agent.id,
        parent_agent_id=None,
        name="root",
        description="",
        configuration=None,
    )
    try:
        handles: list[Run] = []
        with pytest.raises(RunFailed):
            run_agent(
                agent,
                max_steps=1,
                messages=[UserMessage(content="Check evidence")],
                runs=handles,
            )
        snapshot = handles[0].snapshot()
        set_agent_transcript(
            message, snapshot.transcript(), db_session=db_session, persist_content=True
        )
        db_session.flush()
        db_session.expire(message)
        db_session.refresh(message, ["agent_runs"])
        stored = read_root_transcript(message)
        assert stored is not None and stored.status == RunStatus.ERROR
        assert stored.failure is not None
        assert stored.failure.kind == RunFailureKind.EXECUTION
        assert sensitive_detail not in stored.model_dump_json()
    finally:
        db_session.rollback()


@pytest.mark.parametrize("ancestor_first", [True, False])
def test_history_keeps_captured_base_when_ancestor_finishes_later(
    db_session: Session, ancestor_first: bool
) -> None:
    session = ChatSession(id=uuid4(), description="history provenance")
    db_session.add(session)
    db_session.flush()
    messages: list[ChatMessage] = []
    for _ in range(3):
        message = ChatMessage(
            chat_session_id=session.id,
            parent_message_id=messages[-1].id if messages else None,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add(message)
        db_session.flush()
        messages.append(message)
    db_session.commit()
    root_id = get_or_create_root_agent(messages[0].id, str(uuid4()))
    run_ids = [str(uuid4()) for _ in messages]
    try:
        for index in [0, *([1, 2] if ancestor_first else [2, 1])]:
            with get_session_with_current_tenant() as writer:
                message = writer.get(ChatMessage, messages[index].id)
                assert message is not None
                set_agent_transcript(
                    message,
                    AgentTranscript(
                        agent_id=root_id,
                        run_id=run_ids[index],
                        previous_run_id=run_ids[0] if index else None,
                        status=RunStatus.COMPLETE,
                        messages=[
                            AssistantMessage(content=[TextContent(text=str(index))])
                        ],
                    ),
                    db_session=writer,
                    persist_content=True,
                )
                writer.commit()
        restored = load_agent_history(messages[2].id, root_id)
        assert [run.run_id for run in restored.transcripts] == [run_ids[0], run_ids[2]]
        assert [run.messages[0].text for run in restored.transcripts] == ["0", "2"]
        ancestor = load_agent_history(messages[1].id, root_id)
        assert [run.run_id for run in ancestor.transcripts] == run_ids[:2]
    finally:
        db_session.execute(
            delete(ChatMessage).where(ChatMessage.chat_session_id == session.id)
        )
        db_session.delete(session)
        db_session.commit()


def test_terminal_publication_rolls_back_agent_registration(
    db_session: Session,
) -> None:
    session = ChatSession(id=uuid4(), description="atomic publication")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(message)
    db_session.commit()
    root_id = get_or_create_root_agent(message.id, str(uuid4()))
    child_id, root_run, child_run = (str(uuid4()) for _ in range(3))
    transcript = AgentTranscript(
        agent_id=root_id,
        run_id=root_run,
        status=RunStatus.CANCELLED,
        messages=[],
        child_runs=[
            AgentTranscript(
                agent_id=child_id,
                agent_path="/root/research",
                run_id=child_run,
                status=RunStatus.CANCELLED,
                messages=[],
            )
        ],
    )
    try:
        with get_session_with_current_tenant() as writer:
            response = writer.get(ChatMessage, message.id)
            assert response is not None
            set_agent_transcript(
                response, transcript, db_session=writer, persist_content=True
            )
            assert writer.get(ChatSessionAgent, child_id) is not None
            writer.rollback()
        assert db_session.get(ChatSessionAgent, child_id) is None
        assert db_session.get(AgentRun, root_run) is None
        set_agent_transcript(
            message, transcript, db_session=db_session, persist_content=True
        )
        db_session.commit()
        assert db_session.get(ChatSessionAgent, child_id) is not None
        saved = load_agent_history(message.id, child_id)
        assert saved.transcripts[0].status == RunStatus.CANCELLED
        with pytest.raises(ValueError, match="already has"):
            set_agent_transcript(
                message, transcript, db_session=db_session, persist_content=True
            )
        db_session.rollback()
    finally:
        db_session.execute(
            delete(ChatMessage).where(ChatMessage.chat_session_id == session.id)
        )
        db_session.delete(session)
        db_session.commit()


def test_parallel_branches_publish_distinct_agents_with_same_name(
    db_session: Session,
) -> None:
    session = ChatSession(id=uuid4(), description="parallel branches")
    db_session.add(session)
    db_session.flush()
    anchor = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(anchor)
    db_session.flush()
    branches = [
        ChatMessage(
            chat_session_id=session.id,
            parent_message_id=anchor.id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        for _ in range(2)
    ]
    db_session.add_all(branches)
    db_session.commit()
    with ContextThreadPoolExecutor(max_workers=2) as executor:
        roots = [
            executor.submit(
                lambda message_id=message.id: get_or_create_root_agent(
                    message_id, str(uuid4())
                )
            )
            for message in branches
        ]
        root_ids = [future.result(timeout=10) for future in roots]
    assert root_ids[0] == root_ids[1]
    root_id = root_ids[0]
    child_ids = [str(uuid4()), str(uuid4())]

    def save_branch(message_id: int, child_id: str) -> None:
        with get_session_with_current_tenant() as writer:
            message = writer.get(ChatMessage, message_id)
            assert message is not None
            set_agent_transcript(
                message,
                AgentTranscript(
                    agent_id=root_id,
                    run_id=str(uuid4()),
                    status=RunStatus.COMPLETE,
                    messages=[],
                    child_runs=[
                        AgentTranscript(
                            agent_id=child_id,
                            agent_path="/root/research",
                            run_id=str(uuid4()),
                            status=RunStatus.COMPLETE,
                            messages=[],
                        )
                    ],
                ),
                db_session=writer,
                persist_content=True,
            )
            writer.commit()

    try:
        with ContextThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    lambda message_id=message.id, child_id=child_id: save_branch(
                        message_id, child_id
                    )
                )
                for message, child_id in zip(branches, child_ids, strict=True)
            ]
            for future in futures:
                future.result(timeout=10)
        for message, child_id in zip(branches, child_ids, strict=True):
            assert (
                load_agent_history(message.id, child_id).agent_path == "/root/research"
            )
        with pytest.raises(ValueError, match="unavailable"):
            load_agent_history(branches[0].id, child_ids[1])
    finally:
        db_session.execute(
            delete(ChatMessage).where(ChatMessage.chat_session_id == session.id)
        )
        db_session.delete(session)
        db_session.commit()


@pytest.mark.parametrize("ancestor_first", [True, False])
def test_overlapping_turns_save_same_child_labels_by_identity(
    db_session: Session, ancestor_first: bool
) -> None:
    session = ChatSession(id=uuid4(), description="overlapping child labels")
    db_session.add(session)
    db_session.flush()
    messages: list[ChatMessage] = []
    for _ in range(2):
        message = ChatMessage(
            chat_session_id=session.id,
            parent_message_id=messages[-1].id if messages else None,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add(message)
        db_session.flush()
        messages.append(message)
    db_session.commit()
    root_id = get_or_create_root_agent(messages[0].id, str(uuid4()))
    child_ids = [str(uuid4()), str(uuid4())]
    try:
        for index in [0, 1] if ancestor_first else [1, 0]:
            with get_session_with_current_tenant() as writer:
                message = writer.get(ChatMessage, messages[index].id)
                assert message is not None
                set_agent_transcript(
                    message,
                    AgentTranscript(
                        agent_id=root_id,
                        run_id=str(uuid4()),
                        status=RunStatus.COMPLETE,
                        messages=[],
                        child_runs=[
                            AgentTranscript(
                                agent_id=child_ids[index],
                                agent_path="/root/research",
                                run_id=str(uuid4()),
                                status=RunStatus.COMPLETE,
                                messages=[
                                    AssistantMessage(
                                        content=[TextContent(text=str(index))]
                                    )
                                ],
                            )
                        ],
                    ),
                    db_session=writer,
                    persist_content=True,
                )
                writer.commit()
        for index, child_id in enumerate(child_ids):
            restored = load_agent_history(messages[1].id, child_id)
            assert restored.agent_path == "/root/research"
            assert restored.parent_agent_id == root_id
            assert restored.transcripts[0].messages[0].text == str(index)
        with pytest.raises(ValueError, match="unavailable"):
            load_agent_history(messages[0].id, child_ids[1])
    finally:
        db_session.execute(
            delete(ChatMessage).where(ChatMessage.chat_session_id == session.id)
        )
        db_session.delete(session)
        db_session.commit()


@pytest.mark.parametrize("tool_kind", ["python", "coding"])
def test_completed_tool_display_matches_reload_without_duplicate_streamed_output(
    db_session: Session, tool_kind: str
) -> None:
    from queue import Queue

    from onyx.agents.events import ToolEndEvent, ToolStartEvent, ToolUpdateEvent
    from onyx.agents.tools import ToolProgress
    from onyx.chat.emitter import Emitter
    from onyx.chat.presentation import ResponsePresenter
    from onyx.llm.models import ToolResult
    from onyx.server.query_and_chat.streaming_models import (
        CodingAgentFinal,
        Packet,
        PythonToolDelta,
    )
    from onyx.tools.models import LlmPythonExecutionResult
    from onyx.tools.progress import CodingCompleted, PythonOutput
    from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
        CodingAgentTool,
    )
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

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
        result = ToolResult(content=output.model_dump_json())
        progress = ToolProgress(details=PythonOutput(stdout="hello "))
        implementation = PythonTool.__name__
    else:
        call = ToolCall(
            id="call",
            name=CodingAgentTool.NAME,
            arguments={"query": "task", "github_repo": "repo"},
        )
        result = ToolResult(content="coding answer")
        progress = ToolProgress(details=CodingCompleted(answer=result.text))
        implementation = CodingAgentTool.__name__
    session = ChatSession(id=uuid4(), description="completed tool display")
    tool = Tool(name=call.name, in_code_tool_id=implementation)
    db_session.add_all([session, tool])
    db_session.flush()
    row = ChatMessage(
        chat_session_id=session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(row)
    db_session.flush()
    agent_id, run_id = str(uuid4()), str(uuid4())
    _seed_agent(
        db_session,
        chat_session_id=session.id,
        creation_message_id=row.id,
        agent_id=agent_id,
        parent_agent_id=None,
        name="root",
        description="",
        configuration=None,
    )
    snapshot = RunSnapshot(
        agent_id=agent_id,
        run_id=run_id,
        status=RunStatus.COMPLETE,
        messages=[
            AssistantMessage(content=[call]),
            ToolResultMessage(
                tool_call_id=call.id, tool_name=call.name, content=result.content
            ),
            AssistantMessage(content=[TextContent(text="done")]),
        ],
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.COMPLETE),
            OperationSnapshot(
                step_index=0,
                message_index=0,
                tool_call_id=call.id,
                status=RunStatus.COMPLETE,
            ),
            OperationSnapshot(step_index=1, message_index=2, status=RunStatus.COMPLETE),
        ],
    )
    db_session.commit()
    queue: Queue[Packet] = Queue()
    presenter = ResponsePresenter(Emitter(queue.put_nowait, response_id=row.id))
    presenter.consume(ToolStartEvent(run_id=run_id, step_index=0, tool_call=call))
    presenter.consume(
        ToolUpdateEvent(run_id=run_id, step_index=0, tool_call=call, progress=progress)
    )
    presenter.consume(
        ToolEndEvent(run_id=run_id, step_index=0, tool_call=call, result=result)
    )
    live: list[Packet] = []
    while not queue.empty():
        packet = queue.get_nowait()
        assert isinstance(packet, Packet)
        live.append(packet)
    projected = project_response(
        snapshot, response_id=row.id, tool_ids={call.name: tool.id}
    )
    save_chat_response(message_id=row.id, response=projected)
    db_session.refresh(row, ["agent_runs", "search_docs"])
    saved = translate_assistant_message_to_packets(row, db_session)
    if tool_kind == "python":
        live_output = [
            packet.obj for packet in live if isinstance(packet.obj, PythonToolDelta)
        ]
        saved_output = [
            packet.obj for packet in saved if isinstance(packet.obj, PythonToolDelta)
        ]
        assert "".join(part.stdout for part in live_output) == "hello world"
        assert "".join(part.stderr for part in live_output) == "warning"
        assert "".join(part.stdout for part in saved_output) == "hello world"
        assert "".join(part.stderr for part in saved_output) == "warning"
    else:
        assert [
            packet.obj.answer
            for packet in live
            if isinstance(packet.obj, CodingAgentFinal)
        ] == ["coding answer"]
        assert [
            packet.obj.answer
            for packet in saved
            if isinstance(packet.obj, CodingAgentFinal)
        ] == ["coding answer"]
