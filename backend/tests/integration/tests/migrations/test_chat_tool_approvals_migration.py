"""Migration 7c00f53ab75f: chat asks for approval of MCP tools, so existing
tools keep running without approval (an ALWAYS workspace policy) unless a
tenant that uses Craft makes their server available in Craft. Existing
workspace policies are kept."""

from collections.abc import Generator

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

PREVIOUS_REVISION = "c4e8a1f2b7d9"


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


def _insert_server(conn: Connection, name: str, available_in_craft: bool) -> int:
    server_id = conn.execute(
        text(
            "INSERT INTO mcp_server (owner, name, server_url, available_in_craft) "
            "VALUES ('admin@example.com', :name, 'https://example.com/mcp', "
            ":available_in_craft) RETURNING id"
        ),
        {"name": name, "available_in_craft": available_in_craft},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO tool (name, mcp_server_id, enabled) "
            "VALUES ('read', :id, true), ('write', :id, true)"
        ),
        {"id": server_id},
    )
    return server_id


def _policies(conn: Connection, server_id: int) -> dict[str, str]:
    return dict(
        conn.execute(
            text(
                "SELECT policy.action_id, policy.policy "
                "FROM workspace_action_policy AS policy "
                "JOIN gated_app ON gated_app.id = policy.gated_app_id "
                "WHERE gated_app.mcp_server_id = :id"
            ),
            {"id": server_id},
        )
        .tuples()
        .all()
    )


@pytest.fixture(params=[False, True], ids=["no_craft_history", "craft_history"])
def craft_history(
    request: pytest.FixtureRequest, engine: Engine
) -> Generator[bool, None, None]:
    yield request.param
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.begin() as conn:
        # Cascades to the servers' tools, app identities and policies.
        conn.execute(text("DELETE FROM mcp_server"))
        conn.execute(text("DELETE FROM build_session"))


def test_existing_mcp_tools_keep_running_without_approval_in_chat(
    engine: Engine, craft_history: bool
) -> None:
    with engine.begin() as conn:
        if craft_history:
            conn.execute(
                text("INSERT INTO build_session (id) VALUES (gen_random_uuid())")
            )
        chat_only = _insert_server(conn, "chat-only", available_in_craft=False)
        in_craft = _insert_server(conn, "in-craft", available_in_craft=True)
        with_policy = _insert_server(conn, "with-policy", available_in_craft=False)
        gated_app_id = conn.execute(
            text("INSERT INTO gated_app (mcp_server_id) VALUES (:id) RETURNING id"),
            {"id": with_policy},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO workspace_action_policy (gated_app_id, action_id, policy) "
                "VALUES (:id, 'write', 'DENY')"
            ),
            {"id": gated_app_id},
        )

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")

    with engine.connect() as conn:
        assert _policies(conn, chat_only) == {"read": "ALWAYS", "write": "ALWAYS"}
        assert _policies(conn, in_craft) == (
            {} if craft_history else {"read": "ALWAYS", "write": "ALWAYS"}
        )
        assert _policies(conn, with_policy) == {"read": "ALWAYS", "write": "DENY"}
