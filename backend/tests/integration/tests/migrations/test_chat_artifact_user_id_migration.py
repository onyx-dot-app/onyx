"""Migration 4d900adc4242 gives each chat artifact its chat's owner, deletes
the artifacts of a chat without one with their file records, and indexes a user's artifacts by
latest publish; its downgrade drops the column."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "c828aae2888b"
REVISION = "4d900adc4242"


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


def _file_record(conn: Connection, origin: str) -> str:
    file_id = str(uuid4())
    conn.execute(
        text(
            "INSERT INTO file_record (file_id, display_name, file_origin, "
            "file_type, bucket_name, object_key) "
            "VALUES (:id, 'a.md', :origin, 'text/markdown', 'b', :id)"
        ),
        {"id": file_id, "origin": origin},
    )
    return file_id


def _chat_with_artifact(
    conn: Connection, user_id: UUID | None
) -> tuple[UUID, UUID, list[str]]:
    """A chat of `user_id` with one artifact whose version has a thumbnail:
    the chat's and the artifact's IDs, and the file IDs."""
    chat_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO chat_session (id, user_id, deleted, shared_status, "
            "onyxbot_flow) VALUES (:id, :user_id, false, 'PRIVATE', false)"
        ),
        {"id": chat_id, "user_id": user_id},
    )
    artifact_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO chat_artifact (id, chat_session_id, path) "
            "VALUES (:id, :chat_id, '/w/a.md')"
        ),
        {"id": artifact_id, "chat_id": chat_id},
    )
    file_id = _file_record(conn, "CHAT_ARTIFACT")
    thumbnail_id = _file_record(conn, "CHAT_ARTIFACT_THUMBNAIL")
    conn.execute(
        text(
            "INSERT INTO chat_artifact_version (artifact_id, version, file_id, "
            "thumbnail_file_id) VALUES (:artifact_id, 1, :file_id, :thumbnail_id)"
        ),
        {"artifact_id": artifact_id, "file_id": file_id, "thumbnail_id": thumbnail_id},
    )
    return chat_id, artifact_id, [file_id, thumbnail_id]


def _remaining(conn: Connection, file_ids: list[str]) -> set[str]:
    return set(
        conn.execute(
            text("SELECT file_id FROM file_record WHERE file_id = ANY(:ids)"),
            {"ids": file_ids},
        ).scalars()
    )


def test_the_upgrade_fills_the_owner_and_the_downgrade_drops_it(
    engine: Engine,
) -> None:
    user_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO "user" (id, email, hashed_password, is_active, '
                "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true)"
            ),
            {"id": user_id, "email": f"artifact-owner-{user_id.hex[:8]}@example.com"},
        )
        owned_chat, owned, owned_files = _chat_with_artifact(conn, user_id)
        ownerless_chat, ownerless, ownerless_files = _chat_with_artifact(conn, None)
    try:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
        with engine.connect() as conn:
            owners = {
                row.id: row.user_id
                for row in conn.execute(
                    text("SELECT id, user_id FROM chat_artifact WHERE id IN (:a, :b)"),
                    {"a": owned, "b": ownerless},
                )
            }
            index = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_chat_artifact_user_id_updated_at'"
                )
            ).scalar_one()
            index_valid = conn.execute(
                text(
                    "SELECT indisvalid FROM pg_index WHERE indexrelid = "
                    "'ix_chat_artifact_user_id_updated_at'::regclass"
                )
            ).scalar_one()
            # "c": deleting the user deletes the artifact, as it does the chat.
            # The upgrade adds the key NOT VALID, then validates it.
            delete_rule = tuple(
                conn.execute(
                    text(
                        "SELECT confdeltype::text, convalidated FROM pg_constraint "
                        "WHERE conname = 'chat_artifact_user_id_fkey'"
                    )
                ).one()
            )
            remaining = _remaining(conn, owned_files + ownerless_files)
        assert owners == {owned: user_id}
        # The ownerless chat's file records go with its artifact, thumbnail
        # included; the owned ones stay.
        assert remaining == set(owned_files)
        assert "(user_id, updated_at DESC)" in index
        assert index_valid
        assert delete_rule == ("c", True)

        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
        )
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'chat_artifact' AND column_name = 'user_id'"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM chat_session WHERE id IN (:a, :b)"),
                {"a": owned_chat, "b": ownerless_chat},
            )
            conn.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": user_id})
            conn.execute(
                text("DELETE FROM file_record WHERE file_id = ANY(:ids)"),
                {"ids": owned_files + ownerless_files},
            )
