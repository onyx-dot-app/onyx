"""Migration 170d8004af5b: each published file gets a chat_artifact row with
the root chat from its file ID (`chat-artifact-<chat ID>-<hex>`) and the path
and title from its file record's metadata. A file without a path gets a row
without one, so its chat's readers keep their access. A file whose chat no
longer exists and other files get no row."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.chat import get_chat_published_files
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.models import User
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "e08a3dc8052a"


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
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


def _insert_user(conn: Connection) -> UUID:
    user_id = uuid4()
    conn.execute(
        text(
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true)"
        ),
        {"id": user_id, "email": f"artifact-{user_id.hex[:8]}@example.com"},
    )
    return user_id


def _insert_chat(conn: Connection, user_id: UUID) -> UUID:
    chat_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO chat_session (id, user_id, onyxbot_flow, deleted, "
            "shared_status) VALUES (:id, :user_id, false, false, 'PRIVATE')"
        ),
        {"id": chat_id, "user_id": user_id},
    )
    return chat_id


def _insert_file(
    conn: Connection,
    file_id: str,
    origin: str,
    metadata: str | None,
    age_seconds: int = 0,
) -> None:
    conn.execute(
        text(
            "INSERT INTO file_record (file_id, display_name, file_origin, "
            "file_type, file_metadata, bucket_name, object_key, created_at) "
            "VALUES (:file_id, 'a.md', :origin, 'text/markdown', "
            "CAST(:metadata AS jsonb), 'bucket', :file_id, "
            "now() - make_interval(secs => :age_seconds))"
        ),
        {
            "file_id": file_id,
            "origin": origin,
            "metadata": metadata,
            "age_seconds": age_seconds,
        },
    )


def test_upgrade_links_published_files_to_their_chat(engine: Engine) -> None:
    with engine.begin() as conn:
        owner_id = _insert_user(conn)
        chat_id = _insert_chat(conn, owner_id)
        titled = f"chat-artifact-{chat_id}-{uuid4().hex}"
        untitled = f"chat-artifact-{chat_id}-{uuid4().hex}"
        no_path = f"chat-artifact-{chat_id}-{uuid4().hex}"
        gone_chat = f"chat-artifact-{uuid4()}-{uuid4().hex}"
        not_a_chat = "chat-artifact-not-a-uuid"
        image = f"chat-artifact-{chat_id}-image"
        _insert_file(
            conn,
            titled,
            "CHAT_ARTIFACT",
            '{"chat_session_id": "x", "published_path": "/w/a.md", '
            '"published_title": "Report"}',
            # Older than `untitled`, so the list order does not tie
            age_seconds=60,
        )
        _insert_file(conn, untitled, "CHAT_ARTIFACT", '{"published_path": "/w/b.md"}')
        _insert_file(conn, no_path, "CHAT_ARTIFACT", '{"chat_session_id": "x"}')
        _insert_file(conn, gone_chat, "CHAT_ARTIFACT", '{"published_path": "/w/c.md"}')
        _insert_file(conn, not_a_chat, "CHAT_ARTIFACT", '{"published_path": "/w/d.md"}')
        _insert_file(conn, image, "CHAT_IMAGE_GEN", '{"published_path": "/w/e.md"}')

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.file_id, a.chat_session_id, a.path, a.title, "
                "a.created_at = f.created_at "
                "FROM chat_artifact a JOIN file_record f USING (file_id) "
                "ORDER BY a.path"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        (titled, chat_id, "/w/a.md", "Report", True),
        (untitled, chat_id, "/w/b.md", None, True),
        (no_path, chat_id, None, None, True),
    ]
    with Session(engine) as db_session:
        owner = db_session.get_one(User, owner_id)
        # The chat's owner keeps access to the file without a path, and the
        # chat's file list leaves it out.
        assert user_can_access_chat_file(no_path, owner, db_session)
        assert [
            file.file_id for file in get_chat_published_files(chat_id, db_session)
        ] == [titled, untitled]

    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT to_regclass('chat_artifact')")).scalar_one()
            is None
        )
