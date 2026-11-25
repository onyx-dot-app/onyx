"""Migration c14c2689b392 makes the existing chat artifacts of live chats
PENDING, so the indexing beat indexes the files published before it, and
those of deleted chats REMOVED."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "78852b5a0db6"
REVISION = "c14c2689b392"


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )
    try:
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


def test_existing_artifacts_become_pending_or_removed(engine: Engine) -> None:
    user_id = uuid4()
    chat_id = uuid4()
    artifact_id = uuid4()
    deleted_chat_id = uuid4()
    removed_artifact_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO "user" (id, email, hashed_password, is_active, '
                "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true)"
            ),
            {"id": user_id, "email": f"artifact-index-{user_id.hex[:8]}@example.com"},
        )
        for chat, artifact, deleted in (
            (chat_id, artifact_id, False),
            (deleted_chat_id, removed_artifact_id, True),
        ):
            conn.execute(
                text(
                    "INSERT INTO chat_session (id, user_id, deleted, shared_status, "
                    "onyxbot_flow) VALUES (:id, :user_id, :deleted, 'PRIVATE', false)"
                ),
                {"id": chat, "user_id": user_id, "deleted": deleted},
            )
            conn.execute(
                text(
                    "INSERT INTO chat_artifact (id, chat_session_id, user_id, path) "
                    "VALUES (:id, :chat_id, :user_id, '/w/a.md')"
                ),
                {"id": artifact, "chat_id": chat, "user_id": user_id},
            )
    try:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
        with engine.connect() as conn:
            rows = {
                row.id: (row.index_status, row.index_attempts)
                for row in conn.execute(
                    text(
                        "SELECT id, index_status, index_attempts FROM "
                        "chat_artifact WHERE user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
            }
        assert rows == {
            artifact_id: ("PENDING", 0),
            removed_artifact_id: ("REMOVED", 0),
        }
        # The later migrations run on the seeded rows.
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM chat_session WHERE id IN (:id, :deleted_id)"),
                {"id": chat_id, "deleted_id": deleted_chat_id},
            )
            conn.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": user_id})
