"""Chat input migration preserves draining readers and restores both preference values."""

from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema, DropSchema


def test_chat_inputs_upgrade_downgrade_upgrade(isolated_engine: Engine) -> None:
    schema = f"chat_inputs_{uuid4().hex}"
    with isolated_engine.connect() as connection:
        try:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text("SELECT set_config('search_path', :schema, false)"),
                {"schema": schema},
            )
            connection.execute(
                text("""
                CREATE TABLE "user" (id integer PRIMARY KEY, paste_as_tile boolean);
                CREATE TABLE chat_session (id uuid PRIMARY KEY);
                CREATE TABLE chat_message (id integer PRIMARY KEY);
                CREATE TABLE tool_call (id integer PRIMARY KEY);
                CREATE TABLE chat_response_item (id varchar PRIMARY KEY);
                INSERT INTO "user" VALUES (1, true), (2, false);
            """)
            )
            scripts = ScriptDirectory(
                str(Path(__file__).resolve().parents[3] / "alembic")
            )
            revision = scripts.get_revision("b7a9d1e3f502")
            assert revision is not None
            with Operations.context(MigrationContext.configure(connection)):
                revision.module.upgrade()
                # Old user queries remain valid while the deployment drains.
                assert connection.execute(
                    text(
                        'SELECT id, paste_as_tile, ui_preferences FROM "user" ORDER BY id'
                    )
                ).all() == [(1, True, {"paste_as_tile": True}), (2, False, {})]
                connection.execute(
                    text("""
                    UPDATE "user" SET ui_preferences = '{"paste_as_tile": false}' WHERE id = 1;
                    UPDATE "user" SET ui_preferences = '{"paste_as_tile": true}' WHERE id = 2;
                """)
                )
                revision.module.downgrade()
                assert connection.execute(
                    text('SELECT id, paste_as_tile FROM "user" ORDER BY id')
                ).all() == [(1, False), (2, True)]
                revision.module.upgrade()
                assert connection.execute(
                    text('SELECT id, ui_preferences FROM "user" ORDER BY id')
                ).all() == [(1, {}), (2, {"paste_as_tile": True})]
        finally:
            connection.rollback()
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(text("RESET search_path"))
            connection.commit()
