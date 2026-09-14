"""Canonical output survives database storage and legacy display projection."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, Column, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from onyx.agents.transcript import AgentTranscript
from onyx.chat.compression import _build_summary_messages
from onyx.configs.constants import MessageType
from onyx.db.agent_transcript import read_agent_transcript
from onyx.db.chat import reserve_chat_response_ids
from onyx.db.chat_history import convert_chat_history
from onyx.db.chat_response import save_chat_turn
from onyx.db.models import ChatMessage, ChatSession
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)


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
                chat_history=[row],
                files=[],
                context_image_files=[],
                additional_context=None,
                token_counter=len,
                tool_id_to_name_map={},
            ).messages
            assert history == transcript.messages
            assert _build_summary_messages([row], {}) == transcript.messages
            assert history[-1].text == "Raw answer [1]."
        else:
            assert stored is None
            assert row.message == ""
            assert row.reasoning_tokens is None
            assert _build_summary_messages([row], {}) == []
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
            chat_history=[row],
            files=[],
            context_image_files=[],
            additional_context=None,
            token_counter=len,
            tool_id_to_name_map={},
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


def test_environment_setting_removal_is_reversible(db_session: Session) -> None:
    schema = f"setting_migration_{uuid4().hex}"
    connection = db_session.connection()
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(
            text("SELECT set_config('search_path', :schema, true)"), {"schema": schema}
        )
        settings = Table(
            "security_settings",
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column("llm_custom_config_env_injection", Boolean, nullable=True),
        )
        settings.create(connection)
        connection.execute(
            settings.insert().values(id=1, llm_custom_config_env_injection=True)
        )
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
        revision = scripts.get_revision("7930b74f92fb")
        assert revision is not None
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
            assert [
                column["name"]
                for column in inspect(connection).get_columns(
                    "security_settings", schema=schema
                )
            ] == ["id"]
            revision.module.downgrade()
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns(
                    "security_settings", schema=schema
                )
            }
            assert columns["llm_custom_config_env_injection"]["nullable"]
            assert (
                connection.scalar(select(settings.c.llm_custom_config_env_injection))
                is None
            )
            revision.module.upgrade()
            assert [
                column["name"]
                for column in inspect(connection).get_columns(
                    "security_settings", schema=schema
                )
            ] == ["id"]
            assert connection.scalar(select(settings.c.id)) == 1
    finally:
        db_session.rollback()
