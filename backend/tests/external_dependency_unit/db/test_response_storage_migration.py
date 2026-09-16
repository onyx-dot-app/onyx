"""The response-item migration preserves main's public response records."""

from pathlib import Path
from uuid import uuid4

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
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema


def test_response_storage_upgrade_downgrade_upgrade(db_session: Session) -> None:
    schema = f"response_migration_{uuid4().hex}"
    connection = db_session.connection()
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(
            text("SELECT set_config('search_path', :schema, true)"), {"schema": schema}
        )
        metadata = MetaData()
        Table(
            "chat_session", metadata, Column("id", UUID(as_uuid=True), primary_key=True)
        )
        messages = Table(
            "chat_message",
            metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "chat_session_id",
                UUID(as_uuid=True),
                ForeignKey("chat_session.id", name="chat_message_chat_session_id_fkey"),
            ),
            Column("message", Text, nullable=False),
            Column("message_type", String(9), nullable=False),
            Column("parent_message_id", Integer, ForeignKey("chat_message.id")),
            Column("latest_child_message_id", Integer, ForeignKey("chat_message.id")),
            Column(
                "last_summarized_message_id",
                Integer,
                ForeignKey("chat_message.id", ondelete="SET NULL"),
            ),
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
                message_type="ASSISTANT",
                last_summarized_message_id=42,
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
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
        revision = scripts.get_revision("7a03b6e90c12")
        assert revision is not None
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
            assert (
                connection.scalar(
                    text("SELECT message_type FROM chat_message WHERE id=43")
                )
                == "SUMMARY"
            )
            assert "parent_session_id" not in {
                column["name"]
                for column in inspect(connection).get_columns(
                    "chat_session", schema=schema
                )
            }
            assert "chat_response_item" in inspect(connection).get_table_names(
                schema=schema
            )
            assert "agent_run" not in inspect(connection).get_table_names(schema=schema)
            assert not {
                "input_content",
                "message_kind",
                "summary_message_id",
                "invocation_index",
            } & {
                column["name"]
                for column in inspect(connection).get_columns(
                    "chat_message", schema=schema
                )
            }
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
                    (11, :root, 42, 1, '', '{"content": [{"type": "text", "text": "Saved result"}]}');
                INSERT INTO chat_message (id, chat_session_id, parent_message_id, message, message_type, summary_covered_count, summary_covered_digest) VALUES
                    (44, :root, 42, 'SDK summary', 'SUMMARY', 2, 'coverage');
                INSERT INTO chat_response_item (id, chat_message_id, position, step_index, kind, content) VALUES
                    ('leaf-text', 202, 0, 0, 'text', '{"type": "text", "text": "Grandchild output"}');
                INSERT INTO chat_feedback (id, chat_message_id) VALUES (1, 202);
                INSERT INTO search_doc (id) VALUES (1);
                INSERT INTO tool_call__search_doc VALUES (9, 1);
                INSERT INTO chat_message__search_doc VALUES (202, 1);
            """),
                {"root": root_id, "child": child_id, "grandchild": grandchild_id},
            )
            revision.module.downgrade()
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
                connection.scalar(text("SELECT count(*) FROM tool_call__search_doc"))
                == 0
            )
            assert (
                connection.scalar(text("SELECT count(*) FROM chat_message__search_doc"))
                == 0
            )
            assert connection.execute(
                text(
                    "SELECT message_type, last_summarized_message_id FROM chat_message WHERE id=43"
                )
            ).one() == ("ASSISTANT", 42)
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
                connection.scalar(text("SELECT message FROM chat_message WHERE id=42"))
                == "Existing answer"
            )
            assert (
                connection.scalar(
                    text("SELECT tool_call_response FROM tool_call WHERE id=7")
                )
                == "Existing result"
            )
            revision.module.upgrade()
            assert (
                connection.scalar(
                    text("SELECT message_type FROM chat_message WHERE id=43")
                )
                == "SUMMARY"
            )
            assert "parent_session_id" not in {
                column["name"]
                for column in inspect(connection).get_columns(
                    "chat_session", schema=schema
                )
            }
            assert "chat_response_item" in inspect(connection).get_table_names(
                schema=schema
            )
    finally:
        db_session.rollback()
