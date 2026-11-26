"""Migration 00a73eb4dccf lets an action_approval row belong to a command in a
chat's VM. The upgrade keeps the Craft approval rows; a downgrade (a version
rollback) removes only the command rows, which the older release cannot
read, and keeps every app, credential and Craft approval."""

import json
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
from onyx.utils.encryption import encrypt_string_to_bytes
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "a4253e609025"
REVISION = "00a73eb4dccf"

# The rows a rollback must keep, by table and order column.
KEPT_TABLES = {
    "integration": "id",
    "integration_connection": "id",
    "api_app": "id",
    "tool": "id",
    "approval_request": "id",
}


def _migrate(direction: str, revision: str) -> None:
    if direction == "upgrade":
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=revision)
    else:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=revision
        )


class _Seeds:
    """The rows a test commits, deleted at teardown."""

    def __init__(self) -> None:
        self.user_ids: list[UUID] = []
        self.integration_ids: list[int] = []

    def delete(self, engine: Engine) -> None:
        with engine.begin() as conn:
            apps = conn.execute(
                text(
                    "SELECT tool_id, api_app_id FROM integration WHERE id = ANY(:ids)"
                ),
                {"ids": self.integration_ids},
            ).all()
            for statement in (
                "DELETE FROM action_approval WHERE integration_id = ANY(:ids)",
                "DELETE FROM integration_connection WHERE integration_id = ANY(:ids)",
                "DELETE FROM integration WHERE id = ANY(:ids)",
            ):
                conn.execute(text(statement), {"ids": self.integration_ids})
            conn.execute(
                text("DELETE FROM tool WHERE id = ANY(:ids)"),
                {"ids": [tool_id for tool_id, _ in apps]},
            )
            conn.execute(
                text("DELETE FROM api_app WHERE id = ANY(:ids)"),
                {"ids": [app_id for _, app_id in apps]},
            )
            for statement in (
                "DELETE FROM chat_session WHERE user_id = ANY(:ids)",
                "DELETE FROM build_session WHERE user_id = ANY(:ids)",
                'DELETE FROM "user" WHERE id = ANY(:ids)',
            ):
                conn.execute(text(statement), {"ids": self.user_ids})


@pytest.fixture
def seeds() -> _Seeds:
    return _Seeds()


@pytest.fixture
def engine(seeds: _Seeds) -> Generator[Engine, None, None]:
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
            seeds.delete(engine)
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


def _insert_rest_app(conn: Connection) -> int:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "t", "description": "t", "version": "1"},
        "servers": [{"url": "https://orders.example.com"}],
        "paths": {"/orders": {"get": {"operationId": "listOrders", "summary": "L"}}},
    }
    tool_id = conn.execute(
        text(
            "INSERT INTO tool (name, description, display_name, openapi_schema, "
            "passthrough_auth, enabled) VALUES (:name, 'd', :name, "
            "CAST(:spec AS jsonb), false, true) RETURNING id"
        ),
        {"name": f"orders_{uuid4().hex[:8]}", "spec": json.dumps(spec)},
    ).scalar_one()
    app_id = conn.execute(
        text(
            "INSERT INTO api_app (api_type, base_url, openapi_document) VALUES "
            "('rest', 'https://orders.example.com', :document) RETURNING id"
        ),
        {"document": json.dumps(spec)},
    ).scalar_one()
    integration_id = conn.execute(
        text(
            "INSERT INTO integration (kind, name, auth_mode, auth_method, "
            "header_template, tool_id, api_app_id) VALUES ('api', :name, "
            "'shared', 'api_key', '{\"X-Api-Key\": \"{api_key}\"}', :tool_id, "
            ":app_id) RETURNING id"
        ),
        {"name": f"orders-{uuid4().hex[:8]}", "tool_id": tool_id, "app_id": app_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO integration_connection (integration_id, user_id, secret, "
            "status) VALUES (:id, NULL, :secret, 'connected')"
        ),
        {
            "id": integration_id,
            "secret": encrypt_string_to_bytes(
                json.dumps({"fields": {"api_key": "org-key"}})
            ),
        },
    )
    return integration_id


def _insert_craft_approval(
    conn: Connection, user_id: UUID, integration_id: int
) -> UUID:
    build_session_id = uuid4()
    conn.execute(
        text("INSERT INTO build_session (id, user_id) VALUES (:id, :user_id)"),
        {"id": build_session_id, "user_id": user_id},
    )
    approval_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO action_approval (approval_id, session_id, payload, actions, "
            "app_name, integration_id) VALUES (:id, :session_id, "
            "'{\"method\": \"POST\"}', '[]', 'orders', :integration_id)"
        ),
        {
            "id": approval_id,
            "session_id": build_session_id,
            "integration_id": integration_id,
        },
    )
    return approval_id


def _approval(conn: Connection, approval_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT to_jsonb(a) - 'chat_session_id' - 'command_id' "
            "FROM action_approval a WHERE approval_id = :id"
        ),
        {"id": approval_id},
    ).scalar_one_or_none()
    return row


def _kept_rows(conn: Connection) -> dict[str, list[Any]]:
    return {
        table: list(
            conn.execute(
                text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY {order_by}")
            ).scalars()
        )
        for table, order_by in KEPT_TABLES.items()
    }


def test_upgrade_keeps_the_craft_approval_rows(engine: Engine, seeds: _Seeds) -> None:
    with engine.begin() as conn:
        user_id = _insert_user(conn)
        integration_id = _insert_rest_app(conn)
        seeds.user_ids.append(user_id)
        seeds.integration_ids.append(integration_id)
        approval_id = _insert_craft_approval(conn, user_id, integration_id)
        before = _approval(conn, approval_id)

    _migrate("upgrade", REVISION)

    with engine.connect() as conn:
        assert _approval(conn, approval_id) == before
        assert conn.execute(
            text(
                "SELECT chat_session_id, command_id FROM action_approval "
                "WHERE approval_id = :id"
            ),
            {"id": approval_id},
        ).one() == (None, None)


def test_a_rollback_drops_only_the_command_rows(engine: Engine, seeds: _Seeds) -> None:
    _migrate("upgrade", REVISION)
    with engine.begin() as conn:
        user_id = _insert_user(conn)
        integration_id = _insert_rest_app(conn)
        seeds.user_ids.append(user_id)
        seeds.integration_ids.append(integration_id)
        craft_approval = _insert_craft_approval(conn, user_id, integration_id)
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
                "command_id, payload, actions, app_name, integration_id) VALUES "
                "(:id, :chat_session_id, :command_id, '{}', '[]', 'orders', "
                ":integration_id)"
            ),
            {
                "id": command_approval,
                "chat_session_id": chat_session_id,
                "command_id": uuid4(),
                "integration_id": integration_id,
            },
        )
        craft_before = _approval(conn, craft_approval)
        kept_before = _kept_rows(conn)

    _migrate("downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        assert _approval(conn, command_approval) is None
        assert _approval(conn, craft_approval) == craft_before
        assert _kept_rows(conn) == kept_before

    _migrate("upgrade", REVISION)
    with engine.connect() as conn:
        assert _approval(conn, craft_approval) == craft_before
        assert _kept_rows(conn) == kept_before
