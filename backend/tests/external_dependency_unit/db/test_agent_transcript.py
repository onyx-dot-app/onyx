"""Canonical output survives database storage and legacy display projection."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from onyx.agents.runtime import RunSnapshot
from onyx.agents.transcript import AgentTranscript, OperationSnapshot, RunStatus
from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.incognito_context import teardown_incognito_session
from onyx.chat.models import ChatResponseSnapshot, MessagePresentation, PresentationMode
from onyx.chat.presentation import project_response
from onyx.configs.constants import MessageType
from onyx.db.agent_transcript import read_agent_transcript, read_chat_execution
from onyx.db.chat import reserve_chat_response_ids
from onyx.db.chat_history import capture_chat_history, convert_chat_history
from onyx.db.chat_response import save_chat_response, save_chat_turn
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatSession, Tool
from onyx.llm.models import (
    AssistantMessage,
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
    transcript = AgentTranscript(
        status="complete",
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
        stored = read_agent_transcript(row)
        if persist_content:
            assert stored == transcript
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
        assert read_agent_transcript(row) is None
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


@pytest.mark.parametrize("names", [["first"], ["first", "second"]])
def test_response_reservation_preserves_model_order_and_active_branch(
    db_session: Session, names: list[str]
) -> None:
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
        legacy = Table(
            "chat_message", MetaData(), Column("id", Integer, primary_key=True)
        )
        legacy.create(connection)
        connection.execute(legacy.insert().values(id=1))
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
        revision = scripts.get_revision("7a03b6e90c12")
        assert revision is not None
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns(
                    "chat_message", schema=schema
                )
            }
            assert columns["agent_transcript"]["nullable"]
            migrated = Table("chat_message", MetaData(), autoload_with=connection)
            assert connection.scalar(select(migrated.c.agent_transcript)) is None
            connection.execute(
                migrated.update()
                .where(migrated.c.id == 1)
                .values(
                    agent_transcript={
                        "version": 1,
                        "status": "complete",
                        "messages": [],
                    }
                )
            )
            assert connection.scalar(select(migrated.c.agent_transcript)) == {
                "version": 1,
                "status": "complete",
                "messages": [],
            }
            revision.module.downgrade()
            assert [
                column["name"]
                for column in inspect(connection).get_columns(
                    "chat_message", schema=schema
                )
            ] == ["id"]
            revision.module.upgrade()
            assert connection.scalar(select(migrated.c.agent_transcript)) is None
            assert connection.scalar(select(legacy.c.id)) == 1
    finally:
        db_session.rollback()


@pytest.mark.parametrize(
    "failed,persist_content", [(False, True), (True, True), (True, False)]
)
def test_saved_execution_keeps_reused_call_ids_and_sibling_children_distinct(
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

    snapshot = RunSnapshot(
        run_id="root",
        input_messages=[UserMessage(content="Root question")],
        status=RunStatus.ERROR if failed else RunStatus.COMPLETE,
        children=[child("left"), child("right")],
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
    )
    db_session.commit()
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
            assert row.agent_transcript is None
            assert not row.tool_calls
            assert not row.search_docs
            assert row.token_count > 0
            return
        assert row.message == "Answer"
        assert row.error == (
            "Provider failed after tool acceptance" if failed else None
        )
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
        stored_transcript = read_agent_transcript(row)
        assert stored_transcript is not None
        assert stored_transcript.input_messages == []
        assert [
            child.input_messages[0].text for child in stored_transcript.children
        ] == ["Task left", "Task right"]
        expected = snapshot.transcript()
        expected.input_messages.clear()
        assert stored_transcript == expected
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
