"""Migration c2caf6a8285c copies each OpenAPI tool row that an integration
points at into api_app and links the integration to it. The rows are seeded
at the revision before it, then the chain upgrades."""

import ast
import importlib.util
import json
import sys
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "4d900adc4242"
REVISION = "c2caf6a8285c"

MIGRATION_PATH = (
    Path(__file__).resolve().parents[4]
    / "alembic"
    / "versions"
    / f"{REVISION}_add_api_app_table.py"
)

# openapi_to_url raises for a spec with several server URLs, so the copy
# gives ''.
WITH_SERVERS = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": [
        {"url": "https://api.example.com/v1"},
        {"url": "https://second.example.com"},
    ],
    "paths": {"/a": {"get": {"operationId": "getA"}}},
}
# Only the orphan tool has this title, so a copy of it is easy to find.
ORPHAN = {
    "openapi": "3.0.0",
    "info": {"title": "api-app-orphan-marker", "version": "1"},
    "servers": [{"url": "https://orphan.example.com"}],
    "paths": {},
}
EMPTY_FIRST_URL = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": [
        {"url": ""},
        {"description": "no url"},
        {"url": "https://e.example.com"},
    ],
    "paths": {},
}
SERVERS_NOT_A_LIST = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": {"url": "https://obj.example.com"},
    "paths": {},
}
URL_NOT_A_STRING = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": [{"url": 5}, {"url": "https://n.example.com"}],
    "paths": {},
}
NO_SERVERS = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "paths": {"/b": {"get": {"operationId": "getB"}}},
}
PASSTHROUGH = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "servers": [{"url": "https://pt.example.com"}],
    "paths": {},
}

# Tool ids: an integration with each OpenAPI shape, an OpenAPI tool with no
# integration, and an integration whose tool row is not OpenAPI.
TOOL_WITH_SERVERS = 990001
TOOL_NO_SERVERS = 990002
TOOL_PASSTHROUGH = 990003
TOOL_ORPHAN = 990004
TOOL_NOT_OPENAPI = 990005
TOOL_EMPTY_FIRST_URL = 990006
TOOL_SERVERS_NOT_A_LIST = 990007
TOOL_URL_NOT_A_STRING = 990008
ALL_TOOLS = [
    TOOL_WITH_SERVERS,
    TOOL_NO_SERVERS,
    TOOL_PASSTHROUGH,
    TOOL_ORPHAN,
    TOOL_NOT_OPENAPI,
    TOOL_EMPTY_FIRST_URL,
    TOOL_SERVERS_NOT_A_LIST,
    TOOL_URL_NOT_A_STRING,
]


def _migrate(direction: str, revision: str) -> None:
    if direction == "upgrade":
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=revision)
    else:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=revision
        )


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
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
        _migrate("upgrade", "head")
        engine.dispose()


def _insert_tool(
    conn: Connection,
    tool_id: int,
    schema: dict[str, Any] | None,
    passthrough_auth: bool = False,
) -> None:
    conn.execute(
        text(
            "INSERT INTO tool (id, name, description, display_name, "
            "in_code_tool_id, openapi_schema, passthrough_auth, enabled) VALUES "
            "(:id, :name, 'd', :name, :in_code, CAST(:schema AS jsonb), "
            ":passthrough, true)"
        ),
        {
            "id": tool_id,
            "name": f"api_app_migration_{tool_id}",
            "in_code": None if schema is not None else "ApiAppMigrationTool",
            "schema": json.dumps(schema) if schema is not None else None,
            "passthrough": passthrough_auth,
        },
    )


def _insert_integration(conn: Connection, tool_id: int, auth_method: str | None) -> int:
    return conn.execute(
        text(
            "INSERT INTO integration (kind, name, auth_mode, auth_method, tool_id) "
            "VALUES ('api', :name, :mode, :method, :tool_id) RETURNING id"
        ),
        {
            "name": f"api_app_migration_{tool_id}",
            "mode": "none" if auth_method is None else "individual",
            "method": auth_method,
            "tool_id": tool_id,
        },
    ).scalar_one()


@pytest.fixture(scope="module")
def seeded(engine: Engine) -> Generator[dict[int, int], None, None]:
    """Integration id by tool id."""
    with engine.begin() as conn:
        _insert_tool(conn, TOOL_WITH_SERVERS, WITH_SERVERS)
        _insert_tool(conn, TOOL_NO_SERVERS, NO_SERVERS)
        _insert_tool(conn, TOOL_PASSTHROUGH, PASSTHROUGH, passthrough_auth=True)
        _insert_tool(conn, TOOL_ORPHAN, ORPHAN)
        _insert_tool(conn, TOOL_NOT_OPENAPI, None)
        _insert_tool(conn, TOOL_EMPTY_FIRST_URL, EMPTY_FIRST_URL)
        _insert_tool(conn, TOOL_SERVERS_NOT_A_LIST, SERVERS_NOT_A_LIST)
        _insert_tool(conn, TOOL_URL_NOT_A_STRING, URL_NOT_A_STRING)
        integrations = {
            TOOL_WITH_SERVERS: _insert_integration(conn, TOOL_WITH_SERVERS, None),
            TOOL_NO_SERVERS: _insert_integration(conn, TOOL_NO_SERVERS, None),
            TOOL_PASSTHROUGH: _insert_integration(conn, TOOL_PASSTHROUGH, "onyx_login"),
            TOOL_NOT_OPENAPI: _insert_integration(conn, TOOL_NOT_OPENAPI, None),
            **{
                tool_id: _insert_integration(conn, tool_id, None)
                for tool_id in (
                    TOOL_EMPTY_FIRST_URL,
                    TOOL_SERVERS_NOT_A_LIST,
                    TOOL_URL_NOT_A_STRING,
                )
            },
        }
    _migrate("upgrade", REVISION)
    yield integrations
    with engine.begin() as conn:
        app_ids = conn.execute(
            text(
                "SELECT api_app_id FROM integration "
                "WHERE id = ANY(:ids) AND api_app_id IS NOT NULL"
            ),
            {"ids": list(integrations.values())},
        ).scalars()
        app_id_list = list(app_ids)
        conn.execute(
            text("DELETE FROM integration WHERE id = ANY(:ids)"),
            {"ids": list(integrations.values())},
        )
        conn.execute(
            text("DELETE FROM api_app WHERE id = ANY(:ids)"), {"ids": app_id_list}
        )
        conn.execute(text("DELETE FROM tool WHERE id = ANY(:ids)"), {"ids": ALL_TOOLS})


def _copied(conn: Connection, integration_id: int) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT a.api_type, a.base_url, a.openapi_document, "
                "a.graphql_schema "
                "FROM integration i JOIN api_app a ON a.id = i.api_app_id "
                "WHERE i.id = :id"
            ),
            {"id": integration_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    copied = dict(row)
    copied["openapi_document"] = json.loads(copied["openapi_document"])
    return copied


def _expected(
    seeded: dict[int, int],
) -> dict[int, dict[str, Any] | None]:
    return {
        seeded[TOOL_WITH_SERVERS]: {
            "api_type": "rest",
            "base_url": "",
            "openapi_document": WITH_SERVERS,
            "graphql_schema": None,
        },
        seeded[TOOL_NO_SERVERS]: {
            "api_type": "rest",
            "base_url": "",
            "openapi_document": NO_SERVERS,
            "graphql_schema": None,
        },
        seeded[TOOL_PASSTHROUGH]: {
            "api_type": "rest",
            "base_url": "https://pt.example.com",
            "openapi_document": PASSTHROUGH,
            "graphql_schema": None,
        },
        seeded[TOOL_NOT_OPENAPI]: None,
        seeded[TOOL_EMPTY_FIRST_URL]: {
            "api_type": "rest",
            "base_url": "https://e.example.com",
            "openapi_document": EMPTY_FIRST_URL,
            "graphql_schema": None,
        },
        seeded[TOOL_SERVERS_NOT_A_LIST]: {
            "api_type": "rest",
            "base_url": "",
            "openapi_document": SERVERS_NOT_A_LIST,
            "graphql_schema": None,
        },
        seeded[TOOL_URL_NOT_A_STRING]: {
            "api_type": "rest",
            "base_url": "",
            "openapi_document": URL_NOT_A_STRING,
            "graphql_schema": None,
        },
    }


def _assert_copied(conn: Connection, seeded: dict[int, int]) -> None:
    for integration_id, expected in _expected(seeded).items():
        assert _copied(conn, integration_id) == expected
    # The integration keeps its tool row for the dual-write release.
    tool_ids = dict(
        conn.execute(
            text("SELECT id, tool_id FROM integration WHERE id = ANY(:ids)"),
            {"ids": list(seeded.values())},
        )
        .tuples()
        .all()
    )
    assert tool_ids == {
        integration_id: tool_id for tool_id, integration_id in seeded.items()
    }
    # The tool with no integration gets no row.
    assert (
        conn.execute(
            text("SELECT count(*) FROM api_app WHERE openapi_document LIKE :url"),
            {"url": "%api-app-orphan-marker%"},
        ).scalar_one()
        == 0
    )


def test_copies_each_openapi_integration(
    engine: Engine, seeded: dict[int, int]
) -> None:
    with engine.connect() as conn:
        _assert_copied(conn, seeded)
        index_valid = conn.execute(
            text(
                "SELECT i.indisvalid AND i.indisunique FROM pg_index i "
                "WHERE i.indexrelid = to_regclass('ix_integration_api_app_id')"
            )
        ).scalar_one()
        fk_valid = conn.execute(
            text(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conname = 'fk_integration_api_app'"
            )
        ).scalar_one()
    assert index_valid
    assert fk_valid


def test_new_row_ids_follow_the_copied_ids(
    engine: Engine, seeded: dict[int, int]
) -> None:
    with engine.begin() as conn:
        new_id = conn.execute(
            text(
                "INSERT INTO api_app (api_type, base_url, openapi_document) "
                "VALUES ('rest', '', '{}') RETURNING id"
            )
        ).scalar_one()
        conn.execute(text("DELETE FROM api_app WHERE id = :id"), {"id": new_id})
    copied = [
        integration_id
        for integration_id, expected in _expected(seeded).items()
        if expected is not None
    ]
    assert new_id > max(copied)


@pytest.mark.usefixtures("seeded")
def test_check_ties_columns_to_api_type(engine: Engine) -> None:
    for values in (
        "('rest', '', NULL, NULL)",
        "('rest', '', '{}', 'type Query { a: Int }')",
        "('graphql', '', NULL, NULL)",
        "('graphql', '', '{}', 'type Query { a: Int }')",
        "('soap', '', '{}', NULL)",
    ):
        with engine.connect() as conn:
            with pytest.raises(IntegrityError, match="ck_api_app_definition"):
                conn.execute(
                    text(
                        "INSERT INTO api_app (api_type, base_url, openapi_document, "
                        f"graphql_schema) VALUES {values}"
                    )
                )
            conn.rollback()


def test_downgrade_then_upgrade_gives_the_same_rows(
    engine: Engine, seeded: dict[int, int]
) -> None:
    _migrate("downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('api_app')")).scalar() is None
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'integration' AND column_name = 'api_app_id'"
                )
            ).scalar_one()
            == 0
        )
    _migrate("upgrade", REVISION)
    with engine.connect() as conn:
        _assert_copied(conn, seeded)


def _current_revision(conn: Connection) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


@pytest.mark.usefixtures("seeded")
def test_downgrade_refuses_to_orphan_graphql_apps(engine: Engine) -> None:
    with engine.begin() as conn:
        app_id = conn.execute(
            text(
                "INSERT INTO api_app (api_type, base_url, graphql_schema) "
                "VALUES ('graphql', 'https://gql.example.com', "
                "'type Query { a: Int }') RETURNING id"
            )
        ).scalar_one()
        integration_id = conn.execute(
            text(
                "INSERT INTO integration (kind, name, auth_mode, api_app_id) "
                "VALUES ('api', 'api_app_migration_graphql', 'none', :app_id) "
                "RETURNING id"
            ),
            {"app_id": app_id},
        ).scalar_one()
    try:
        with pytest.raises(
            RuntimeError, match="1 GraphQL app integration.*must delete"
        ):
            _migrate("downgrade", PREVIOUS_REVISION)
        with engine.connect() as conn:
            assert _current_revision(conn) == REVISION
            assert (
                conn.execute(
                    text("SELECT api_app_id FROM integration WHERE id = :id"),
                    {"id": integration_id},
                ).scalar_one()
                == app_id
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM integration WHERE id = :id"), {"id": integration_id}
            )
            conn.execute(text("DELETE FROM api_app WHERE id = :id"), {"id": app_id})


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_app_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_retries_while_integration_is_locked(
    engine: Engine, seeded: dict[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader holds a lock on integration when the upgrade starts. The ALTER
    times out, the reader ends during the retry delay, and the retry
    succeeds."""
    _migrate("downgrade", PREVIOUS_REVISION)
    migration = _load_migration()
    monkeypatch.setattr(migration, "_LOCK_TIMEOUT", "100ms")
    reader = engine.connect()
    reader.execute(text("SELECT count(*) FROM integration"))
    retries: list[float] = []

    def end_the_reader(delay: float) -> None:
        retries.append(delay)
        reader.rollback()

    monkeypatch.setattr(migration.time, "sleep", end_the_reader)
    try:
        with engine.connect() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": REVISION},
            )
            conn.commit()
    finally:
        reader.close()
    assert retries == [migration._RETRY_DELAY_S]
    with engine.connect() as conn:
        _assert_copied(conn, seeded)


def test_migration_imports_no_app_code() -> None:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(MIGRATION_PATH.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    allowed_roots = sys.stdlib_module_names | {"alembic", "sqlalchemy"}
    assert sorted(m for m in modules if m.split(".")[0] not in allowed_roots) == []
