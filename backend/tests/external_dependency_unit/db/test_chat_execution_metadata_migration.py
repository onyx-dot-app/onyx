"""Execution metadata preserves current writers and supports migration reruns."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    delete,
    func,
    inspect,
    literal_column,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.chat.save_chat import save_chat_turn
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_session,
    create_new_chat_message,
    get_or_create_root_message,
    reserve_message_id,
)
from onyx.db.models import ChatMessage, ChatSession, ToolCall
from onyx.db.tools import create_tool_call_no_commit


def test_execution_metadata_upgrade_retry_downgrade_upgrade(
    db_session: Session,
) -> None:
    schema = f"response_migration_{uuid4().hex}"
    with db_session.connection().engine.connect() as connection:
        try:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text("SELECT set_config('search_path', :schema, false)"),
                {"schema": schema},
            )
            metadata = MetaData()
            Table(
                "chat_session",
                metadata,
                Column("id", UUID(as_uuid=True), primary_key=True),
            )
            messages = Table(
                "chat_message",
                metadata,
                Column("id", Integer, primary_key=True),
                Column(
                    "chat_session_id",
                    UUID(as_uuid=True),
                    ForeignKey(
                        "chat_session.id",
                        name="chat_message_chat_session_id_fkey",
                        ondelete="CASCADE",
                    ),
                ),
                Column("message", Text, nullable=False),
                Column("message_type", String(9), nullable=False),
                Column("parent_message_id", Integer, ForeignKey("chat_message.id")),
                Column(
                    "latest_child_message_id", Integer, ForeignKey("chat_message.id")
                ),
                Column("last_summarized_message_id", Text),
                Column(
                    "preferred_response_id",
                    Integer,
                    ForeignKey("chat_message.id", ondelete="SET NULL"),
                ),
            )
            tools = Table(
                "tool_call",
                metadata,
                Column("id", Integer, primary_key=True),
                Column("tool_id", Integer, nullable=False),
                Column("tool_call_response", Text, nullable=False),
                Column(
                    "chat_session_id",
                    UUID(as_uuid=True),
                    ForeignKey("chat_session.id", ondelete="CASCADE"),
                ),
                Column(
                    "parent_chat_message_id",
                    Integer,
                    ForeignKey("chat_message.id", ondelete="CASCADE"),
                ),
                Column(
                    "parent_tool_call_id",
                    Integer,
                    ForeignKey("tool_call.id", ondelete="CASCADE"),
                ),
            )
            Table(
                "chat_feedback",
                metadata,
                Column("id", Integer, primary_key=True),
                Column(
                    "chat_message_id",
                    Integer,
                    ForeignKey("chat_message.id", ondelete="SET NULL"),
                ),
            )
            Table("search_doc", metadata, Column("id", Integer, primary_key=True))
            Table(
                "tool_call__search_doc",
                metadata,
                Column(
                    "tool_call_id",
                    Integer,
                    ForeignKey("tool_call.id", ondelete="CASCADE"),
                    primary_key=True,
                ),
                Column(
                    "search_doc_id",
                    Integer,
                    ForeignKey("search_doc.id", ondelete="CASCADE"),
                    primary_key=True,
                ),
            )
            Table(
                "chat_message__search_doc",
                metadata,
                Column(
                    "chat_message_id",
                    Integer,
                    ForeignKey("chat_message.id", ondelete="CASCADE"),
                    primary_key=True,
                ),
                Column(
                    "search_doc_id",
                    Integer,
                    ForeignKey("search_doc.id", ondelete="CASCADE"),
                    primary_key=True,
                ),
            )
            metadata.create_all(connection)
            root_id, child_id, grandchild_id = uuid4(), uuid4(), uuid4()
            connection.execute(
                text("INSERT INTO chat_session (id) VALUES (:id)"), {"id": root_id}
            )
            connection.execute(
                messages.insert().values(
                    id=42,
                    chat_session_id=root_id,
                    message="Existing answer",
                    message_type="ASSISTANT",
                )
            )
            connection.execute(
                messages.insert().values(
                    id=43,
                    chat_session_id=root_id,
                    parent_message_id=42,
                    message="Existing summary",
                    message_type="SUMMARY",
                    last_summarized_message_id="chat:42",
                )
            )
            connection.execute(
                tools.insert().values(
                    id=7,
                    tool_id=1,
                    tool_call_response="Existing result",
                    chat_session_id=root_id,
                    parent_chat_message_id=42,
                )
            )
            original_fk_oid = connection.scalar(
                text("""
                SELECT oid FROM pg_constraint
                WHERE conrelid = 'chat_message'::regclass
                  AND conname = 'chat_message_chat_session_id_fkey'
            """)
            )
            scripts = ScriptDirectory(
                str(Path(__file__).resolve().parents[3] / "alembic")
            )
            revision = scripts.get_revision("9d8f310ac672")
            items = scripts.get_revision("7a03b6e90c12")
            checkpoints = scripts.get_revision("6b4e821c0a93")
            assert revision is not None
            assert items is not None
            assert checkpoints is not None
            with Operations.context(MigrationContext.configure(connection)):
                items.module.upgrade()
                checkpoints.module.upgrade()
                revision.module.upgrade()
                _assert_response_schema_contract(connection, schema)
                assert connection.execute(
                    text("""
                    SELECT oid, confdeltype FROM pg_constraint
                    WHERE conrelid = 'chat_message'::regclass
                      AND conname = 'chat_message_chat_session_id_fkey'
                """)
                ).one() == (original_fk_oid, "c")
                assert "chat_response_item" in inspect(connection).get_table_names(
                    schema=schema
                )
                # A failed unique build leaves a committed schema and an invalid index.
                connection.execute(
                    text(
                        "ALTER TABLE chat_message DROP CONSTRAINT uq_chat_message_run_id"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE chat_message SET run_id='duplicate' WHERE id IN (42, 43)"
                    )
                )
                connection.commit()
                with pytest.raises(IntegrityError):
                    revision.module.upgrade()
                assert (
                    connection.scalar(
                        text("""
                    SELECT indisvalid FROM pg_index
                    WHERE indexrelid='uq_chat_message_run_id'::regclass
                """)
                    )
                    is False
                )
                connection.execute(
                    text("UPDATE chat_message SET run_id=NULL WHERE id=43")
                )
                revision.module.upgrade()
                assert (
                    connection.scalar(
                        text("""
                    SELECT indisvalid FROM pg_index
                    WHERE indexrelid='uq_chat_message_run_id'::regclass
                """)
                    )
                    is True
                )
                assert connection.execute(
                    text("""
                    SELECT conname FROM pg_constraint
                    WHERE conrelid IN ('chat_message'::regclass, 'chat_session'::regclass)
                      AND conname IN ('fk_chat_session_spawned_by_message', 'fk_chat_message_invocation')
                      AND convalidated
                    ORDER BY conname
                """)
                ).scalars().all() == [
                    "fk_chat_message_invocation",
                    "fk_chat_session_spawned_by_message",
                ]
                connection.execute(
                    text("""
                    INSERT INTO chat_session (id, spawned_by_message_id) VALUES (:child, 42);
                    INSERT INTO chat_message (id, chat_session_id, parent_message_id, message, message_type, invoking_tool_call_id) VALUES
                        (101, :child, NULL, 'Child input', 'USER', 7),
                        (102, :child, 101, 'Child output', 'ASSISTANT', NULL),
                        (103, :child, 102, 'Child follow-up', 'USER', 7),
                        (104, :child, 103, 'Child follow-up output', 'ASSISTANT', NULL);
                    UPDATE chat_message SET latest_child_message_id=102 WHERE id=101;
                    UPDATE chat_message SET preferred_response_id=104 WHERE id=103;
                    INSERT INTO tool_call (id, chat_session_id, parent_chat_message_id, parent_tool_call_id, tool_id, tool_call_response) VALUES
                        (8, :child, 102, 7, 1, 'Nested result');
                    INSERT INTO chat_session (id, spawned_by_message_id) VALUES (:grandchild, 102);
                    INSERT INTO chat_message (id, chat_session_id, parent_message_id, message, message_type, invoking_tool_call_id) VALUES
                        (201, :grandchild, NULL, 'Grandchild input', 'USER', 8),
                        (202, :grandchild, 201, 'Grandchild output', 'ASSISTANT', NULL);
                    INSERT INTO tool_call (id, chat_session_id, parent_chat_message_id, parent_tool_call_id, tool_id, tool_call_response) VALUES
                        (9, :grandchild, 202, 8, 1, 'Leaf result'),
                        (10, :root, 42, NULL, NULL, 'Control result');
                    INSERT INTO tool_call (id, chat_session_id, parent_chat_message_id, tool_id, tool_call_response, result) VALUES
                        (11, :root, 42, 1, '', '{"content": "Saved result"}');
                    INSERT INTO chat_response_item (id, chat_message_id, step_index, generation_status, message) VALUES
                        ('leaf-message', 202, 0, 'complete', '{"role": "assistant", "id": "leaf-message", "content": [{"type": "text", "text": "Grandchild output"}]}');
                    INSERT INTO chat_feedback (id, chat_message_id) VALUES (1, 202);
                    INSERT INTO search_doc (id) VALUES (1);
                    INSERT INTO tool_call__search_doc VALUES (9, 1);
                    INSERT INTO chat_message__search_doc VALUES (202, 1);
                """),
                    {"root": root_id, "child": child_id, "grandchild": grandchild_id},
                )
                connection.execute(
                    text("""
                    INSERT INTO chat_response_item (id, chat_message_id, step_index, generation_status, message)
                    VALUES ('retained-root', 42, 0, 'complete', '{}');
                    INSERT INTO chat_response_checkpoint (chat_message_id, state) VALUES (42, '{}');
                """)
                )
                revision.module.downgrade()
                assert connection.execute(
                    text("SELECT id FROM chat_response_item")
                ).scalars().all() == ["retained-root"]
                assert connection.execute(
                    text("SELECT chat_message_id FROM chat_response_checkpoint")
                ).scalars().all() == [42]
                checkpoints.module.downgrade()
                items.module.downgrade()
                assert connection.execute(
                    text("""
                    SELECT oid, confdeltype FROM pg_constraint
                    WHERE conrelid = 'chat_message'::regclass
                      AND conname = 'chat_message_chat_session_id_fkey'
                """)
                ).one() == (original_fk_oid, "c")
                assert connection.execute(
                    text("SELECT id FROM chat_session")
                ).scalars().all() == [root_id]
                assert connection.execute(
                    text("SELECT id FROM chat_message ORDER BY id")
                ).scalars().all() == [42, 43]
                assert connection.execute(
                    text("SELECT id FROM tool_call ORDER BY id")
                ).scalars().all() == [7, 11]
                assert (
                    connection.scalar(
                        text("SELECT tool_call_response FROM tool_call WHERE id=11")
                    )
                    == "Saved result"
                )
                assert (
                    connection.scalar(
                        text("SELECT chat_message_id FROM chat_feedback WHERE id=1")
                    )
                    is None
                )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM tool_call__search_doc")
                    )
                    == 0
                )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM chat_message__search_doc")
                    )
                    == 0
                )
                assert set(inspect(connection).get_table_names(schema=schema)) == {
                    "chat_session",
                    "chat_message",
                    "tool_call",
                    "chat_feedback",
                    "search_doc",
                    "tool_call__search_doc",
                    "chat_message__search_doc",
                }
                assert (
                    connection.scalar(
                        text("SELECT message FROM chat_message WHERE id=42")
                    )
                    == "Existing answer"
                )
                assert (
                    connection.scalar(
                        text("SELECT tool_call_response FROM tool_call WHERE id=7")
                    )
                    == "Existing result"
                )
                items.module.upgrade()
                checkpoints.module.upgrade()
                revision.module.upgrade()
                assert connection.execute(
                    text("""
                    SELECT oid, confdeltype FROM pg_constraint
                    WHERE conrelid = 'chat_message'::regclass
                      AND conname = 'chat_message_chat_session_id_fkey'
                """)
                ).one() == (original_fk_oid, "c")
                assert "chat_response_item" in inspect(connection).get_table_names(
                    schema=schema
                )
        finally:
            connection.rollback()
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(text("RESET search_path"))
            connection.commit()


def test_current_chat_writers_accept_execution_metadata_schema(
    db_session: Session,
) -> None:
    """Schema preparation must not require the SDK ORM or its writers."""
    chat = create_chat_session(
        db_session=db_session,
        description="Response schema compatibility",
        user_id=None,
        persona_id=None,
    )
    session_id = chat.id
    try:
        root = get_or_create_root_message(session_id, db_session)
        question = create_new_chat_message(
            chat_session_id=session_id,
            parent_message=root,
            message="Question",
            token_count=1,
            message_type=MessageType.USER,
            db_session=db_session,
        )
        answer = reserve_message_id(db_session, session_id, question.id)
        save_chat_turn(
            message_text="Answer",
            reasoning_tokens="Reasoning",
            tool_calls=[],
            citation_to_doc={},
            all_search_docs={},
            db_session=db_session,
            assistant_message=answer,
        )
        call = create_tool_call_no_commit(
            chat_session_id=session_id,
            parent_chat_message_id=answer.id,
            turn_number=0,
            tool_id=1,
            tool_call_id="existing-writer-call",
            tool_call_arguments={"query": "Question"},
            tool_call_response="Existing result",
            tool_call_tokens=1,
            db_session=db_session,
        )
        db_session.commit()
        answer_id, call_id = answer.id, call.id
        db_session.expire_all()
        saved = db_session.get(ChatMessage, answer_id)
        assert saved is not None
        assert (saved.message, saved.reasoning_tokens) == ("Answer", "Reasoning")
        saved_call = db_session.get(ToolCall, call_id)
        assert saved_call is not None
        assert saved_call.tool_call_response == "Existing result"
        assert db_session.execute(
            select(literal_column("response_status"), literal_column("run_id"))
            .select_from(ChatMessage)
            .where(ChatMessage.id == answer_id)
        ).one() == (None, None)
        assert db_session.execute(
            select(literal_column("operation_status"), literal_column("result"))
            .select_from(ToolCall)
            .where(ToolCall.id == call_id)
        ).one() == (None, None)
        response_items = Table(
            "chat_response_item", MetaData(), Column("chat_message_id", Integer)
        )
        assert (
            db_session.scalar(
                select(func.count())
                .select_from(response_items)
                .where(response_items.c.chat_message_id == answer_id)
            )
            == 0
        )
    finally:
        db_session.rollback()
        db_session.execute(delete(ChatSession).where(ChatSession.id == session_id))
        db_session.commit()


def _assert_response_schema_contract(connection: Connection, schema: str) -> None:
    inspector = inspect(connection)
    response_columns = {
        column["name"]
        for column in inspector.get_columns("chat_response_item", schema=schema)
    }
    assert {"message", "generation_status"} <= response_columns
    assert not {"content", "operation_status", "position"} & response_columns
    tool_columns = {
        column["name"] for column in inspector.get_columns("tool_call", schema=schema)
    }
    assert (
        not {"argument_error", "raw_arguments", "arguments_complete", "tool_name"}
        & tool_columns
    )
    assert "ix_chat_response_item_chat_message_id" not in {
        index["name"]
        for index in inspector.get_indexes("chat_response_item", schema=schema)
    }
    assert any(
        index["column_names"] == ["chat_message_id", "step_index"]
        and not index["unique"]
        for index in inspector.get_indexes("chat_response_item", schema=schema)
    )
    checkpoint_columns = {
        column["name"]
        for column in inspector.get_columns("chat_response_checkpoint", schema=schema)
    }
    assert (
        "ownership_version" in checkpoint_columns
        and "revision" not in checkpoint_columns
    )
    connection.execute(
        text("""
        INSERT INTO chat_response_checkpoint (chat_message_id, state) VALUES (42, '{}');
        INSERT INTO chat_response_item (id, chat_message_id, step_index, generation_status, message)
        VALUES ('schema-contract', 42, 0, 'running', '{}');
    """)
    )
    assert (
        connection.scalar(
            text(
                "SELECT ownership_version FROM chat_response_checkpoint WHERE chat_message_id=42"
            )
        )
        == 0
    )
    connection.execute(
        text("""
        DELETE FROM chat_response_checkpoint WHERE chat_message_id=42;
        DELETE FROM chat_response_item WHERE id='schema-contract';
    """)
    )
