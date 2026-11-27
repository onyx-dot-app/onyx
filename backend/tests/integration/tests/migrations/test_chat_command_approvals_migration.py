"""Migration 00a73eb4dccf lets an action_approval row belong to a command in a
chat's VM. The upgrade keeps the Craft approval rows; a downgrade (a version
rollback) removes only the command rows, which the older release cannot
read."""

from collections.abc import Generator
from typing import Any
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

PREVIOUS_REVISION = "933a21d46472"
REVISION = "00a73eb4dccf"


def _migrate(direction: str, revision: str) -> None:
    if direction == "upgrade":
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=revision)
    else:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=revision
        )


@pytest.fixture
def user_ids() -> list[UUID]:
    return []


@pytest.fixture
def engine(user_ids: list[UUID]) -> Generator[Engine, None, None]:
    _migrate("upgrade", "head")
    _migrate("downgrade", PREVIOUS_REVISION)
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
        try:
            _migrate("upgrade", "head")
            # The approval rows go with their sessions.
            with engine.begin() as conn:
                for statement in (
                    "DELETE FROM chat_session WHERE user_id = ANY(:ids)",
                    "DELETE FROM build_session WHERE user_id = ANY(:ids)",
                    'DELETE FROM "user" WHERE id = ANY(:ids)',
                ):
                    conn.execute(text(statement), {"ids": user_ids})
        finally:
            engine.dispose()


def _insert_user(conn: Connection) -> UUID:
    user_id = uuid4()
    conn.execute(
        text(
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) VALUES (:id, :email, '', true, false, true)"
        ),
        {"id": user_id, "email": f"command-approvals-{user_id}@example.com"},
    )
    return user_id


def _insert_craft_approval(conn: Connection, user_id: UUID) -> UUID:
    build_session_id = uuid4()
    conn.execute(
        text("INSERT INTO build_session (id, user_id) VALUES (:id, :user_id)"),
        {"id": build_session_id, "user_id": user_id},
    )
    approval_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO action_approval (approval_id, session_id, payload, actions, "
            "app_name) VALUES (:id, :session_id, '{\"method\": \"POST\"}', '[]', "
            "'orders')"
        ),
        {"id": approval_id, "session_id": build_session_id},
    )
    return approval_id


def _approval(conn: Connection, approval_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        text(
            "SELECT to_jsonb(a) - 'chat_session_id' - 'command_id' "
            "FROM action_approval a WHERE approval_id = :id"
        ),
        {"id": approval_id},
    ).scalar_one_or_none()


def test_a_rollback_drops_only_the_command_rows(
    engine: Engine, user_ids: list[UUID]
) -> None:
    with engine.begin() as conn:
        user_id = _insert_user(conn)
        user_ids.append(user_id)
        craft_approval = _insert_craft_approval(conn, user_id)
        craft_before = _approval(conn, craft_approval)

    _migrate("upgrade", REVISION)
    with engine.begin() as conn:
        assert _approval(conn, craft_approval) == craft_before
        assert conn.execute(
            text(
                "SELECT chat_session_id, command_id FROM action_approval "
                "WHERE approval_id = :id"
            ),
            {"id": craft_approval},
        ).one() == (None, None)
        chat_session_id = uuid4()
        conn.execute(
            text(
                "INSERT INTO chat_session (id, user_id, deleted, shared_status, "
                "onyxbot_flow) VALUES (:id, :user_id, false, 'private', false)"
            ),
            {"id": chat_session_id, "user_id": user_id},
        )
        command_approval = uuid4()
        conn.execute(
            text(
                "INSERT INTO action_approval (approval_id, chat_session_id, "
                "command_id, payload, actions, app_name) VALUES "
                "(:id, :chat_session_id, :command_id, '{}', '[]', 'orders')"
            ),
            {
                "id": command_approval,
                "chat_session_id": chat_session_id,
                "command_id": uuid4(),
            },
        )

    _migrate("downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        assert _approval(conn, command_approval) is None
        assert _approval(conn, craft_approval) == craft_before

    _migrate("upgrade", REVISION)
    with engine.connect() as conn:
        assert _approval(conn, craft_approval) == craft_before
