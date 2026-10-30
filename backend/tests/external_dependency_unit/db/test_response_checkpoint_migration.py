"""Checkpoint migration leaves response items and current writers intact."""

from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema, DropSchema


def test_checkpoint_upgrade_downgrade_upgrade(isolated_engine: Engine) -> None:
    schema = f"response_checkpoint_{uuid4().hex}"
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
                INSERT INTO chat_message VALUES (1), (2);
            """)
            )
            scripts = ScriptDirectory(
                str(Path(__file__).resolve().parents[3] / "alembic")
            )
            items = scripts.get_revision("7a03b6e90c12")
            checkpoint = scripts.get_revision("6b4e821c0a93")
            assert items is not None and checkpoint is not None
            with Operations.context(MigrationContext.configure(connection)):
                items.module.upgrade()
                connection.execute(
                    text("""
                    INSERT INTO chat_response_item (id, chat_message_id, step_index, generation_status, message)
                    VALUES ('retained', 2, 0, 'complete', '{}');
                """)
                )
                checkpoint.module.upgrade()
                connection.execute(
                    text("""
                    INSERT INTO chat_response_checkpoint (chat_message_id, state)
                    VALUES (1, '{"runtime_revision": 7}');
                """)
                )
                assert connection.execute(
                    text(
                        "SELECT ownership_version, state FROM chat_response_checkpoint"
                    )
                ).one() == (0, {"runtime_revision": 7})
                assert {
                    column["name"]
                    for column in inspect(connection).get_columns(
                        "chat_message", schema=schema
                    )
                } == {"id"}
                connection.execute(text("DELETE FROM chat_message WHERE id=1"))
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM chat_response_checkpoint")
                    )
                    == 0
                )
                checkpoint.module.downgrade()
                assert "chat_response_checkpoint" not in inspect(
                    connection
                ).get_table_names(schema=schema)
                assert (
                    connection.scalar(text("SELECT id FROM chat_response_item"))
                    == "retained"
                )
                checkpoint.module.upgrade()
                assert "chat_response_checkpoint" in inspect(
                    connection
                ).get_table_names(schema=schema)
                assert (
                    connection.scalar(text("SELECT id FROM chat_response_item"))
                    == "retained"
                )
        finally:
            connection.rollback()
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(text("RESET search_path"))
            connection.commit()
