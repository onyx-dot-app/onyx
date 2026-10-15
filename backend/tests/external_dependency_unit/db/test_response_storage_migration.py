"""Response item storage preserves existing tables and enforces item identity."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine
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


def test_response_items_upgrade_downgrade_upgrade(isolated_engine: Engine) -> None:
    schema = f"response_items_{uuid4().hex}"
    with isolated_engine.connect() as connection:
        try:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text("SELECT set_config('search_path', :schema, false)"),
                {"schema": schema},
            )
            connection.execute(
                text("""
                CREATE TABLE chat_message (id integer PRIMARY KEY);
                CREATE TABLE tool_call (id integer PRIMARY KEY);
                INSERT INTO chat_message VALUES (1);
                INSERT INTO tool_call VALUES (1);
            """)
            )
            scripts = ScriptDirectory(
                str(Path(__file__).resolve().parents[3] / "alembic")
            )
            revision = scripts.get_revision("7a03b6e90c12")
            assert revision is not None
            with Operations.context(MigrationContext.configure(connection)):
                revision.module.upgrade()
                assert {
                    column["name"]
                    for column in inspect(connection).get_columns(
                        "chat_message", schema=schema
                    )
                } == {"id"}
                assert {
                    column["name"]
                    for column in inspect(connection).get_columns(
                        "tool_call", schema=schema
                    )
                } == {"id"}
                assert "chat_response_checkpoint" not in inspect(
                    connection
                ).get_table_names(schema=schema)
                connection.execute(
                    text("""
                    INSERT INTO chat_response_item (id, chat_message_id, step_index, generation_status, message, is_answer)
                    VALUES ('message', 1, 0, 'complete', '{}', true);
                """)
                )
                columns = {
                    column["name"]: column
                    for column in inspect(connection).get_columns(
                        "chat_response_item", schema=schema
                    )
                }
                assert "tool_call_id" not in columns
                assert not columns["message"]["nullable"]
                assert not columns["generation_status"]["nullable"]
                indexes = {
                    index["name"]: index
                    for index in inspect(connection).get_indexes(
                        "chat_response_item", schema=schema
                    )
                }
                assert set(indexes) == {
                    "uq_response_item_step",
                    "uq_response_item_answer",
                }
                assert indexes["uq_response_item_step"]["unique"]
                assert not indexes["uq_response_item_step"]["dialect_options"].get(
                    "postgresql_where"
                )
                invalid_items = (
                    "('duplicate-step', 1, 0, 'complete', '{}', false)",
                    "('negative-step', 1, -1, 'complete', '{}', false)",
                    "('missing-message', 1, 1, 'complete', NULL, false)",
                    "('missing-status', 1, 1, NULL, '{}', false)",
                    "('second-answer', 1, 1, 'complete', '{}', true)",
                )
                for values in invalid_items:
                    with pytest.raises(IntegrityError), connection.begin_nested():
                        connection.execute(
                            text(
                                "INSERT INTO chat_response_item "
                                "(id, chat_message_id, step_index, generation_status, message, is_answer) "
                                f"VALUES {values}"
                            )
                        )
                connection.execute(text("DELETE FROM tool_call WHERE id=1"))
                assert connection.execute(
                    text("SELECT id FROM chat_response_item")
                ).scalars().all() == ["message"]
                connection.execute(text("DELETE FROM chat_message WHERE id=1"))
                assert (
                    connection.scalar(text("SELECT count(*) FROM chat_response_item"))
                    == 0
                )
                revision.module.downgrade()
                assert set(inspect(connection).get_table_names(schema=schema)) == {
                    "chat_message",
                    "tool_call",
                }
                revision.module.upgrade()
                assert "chat_response_item" in inspect(connection).get_table_names(
                    schema=schema
                )
        finally:
            connection.rollback()
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(text("RESET search_path"))
            connection.commit()


def test_current_chat_writers_accept_response_storage_schema(
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
