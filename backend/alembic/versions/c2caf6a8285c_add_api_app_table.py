"""add api_app table

Revision ID: c2caf6a8285c
Revises: 4d900adc4242
Create Date: 2026-11-23 13:05:12.418390

Adds api_app, the definition of a custom REST or GraphQL app, and
integration.api_app_id. Copies each OpenAPI tool row that an integration
points at into api_app. A GraphQL integration points only at its api_app
row, and its actions have the source 'graphql', so two checks change. The integration keeps its tool_id: for one release
the app writes both rows, so a version rollback still finds the tool row.
"""

import logging
import time
from collections.abc import Callable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision = "c2caf6a8285c"
down_revision = "4d900adc4242"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_integration_api_app_id"
FK_NAME = "fk_integration_api_app"
SINGLE_KIND = "ck_integration_single_kind_row"
ACTION_SOURCE = "ck_integration_action_source"
LOCK_TIMEOUT = "60s"
# Alembic runs all pending revisions of a schema in one transaction, so while
# this retries, the locks of earlier revisions stay held. Keep the budget short.
_LOCK_TIMEOUT = "5s"
_LOCK_ATTEMPTS = 6
_RETRY_DELAY_S = 2
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"

# The id of each copied row is the id of its integration, so the link needs
# no lookup. base_url is the value openapi_to_url gives: the one non-empty
# string url among the servers. Where openapi_to_url raises (no such url,
# several, a server that is not an object, a url that is not a string), the
# spec cannot make a call and the copy gives ''.
_COPY_OPENAPI_TOOLS = """
    INSERT INTO api_app (
        id, api_type, base_url, openapi_document, graphql_schema
    )
    SELECT i.id, 'rest',
        coalesce((
            SELECT min(s.value ->> 'url') FILTER (
                WHERE jsonb_typeof(s.value -> 'url') = 'string'
                AND s.value ->> 'url' <> ''
            )
            FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(t.openapi_schema -> 'servers') = 'array'
                THEN t.openapi_schema -> 'servers' ELSE '[]'::jsonb END
            ) AS s
            HAVING count(*) FILTER (
                WHERE jsonb_typeof(s.value -> 'url') = 'string'
                AND s.value ->> 'url' <> ''
            ) = 1
            AND count(*) FILTER (
                WHERE jsonb_typeof(s.value) <> 'object'
                OR jsonb_typeof(s.value -> 'url') NOT IN ('string', 'null')
            ) = 0
        ), ''),
        t.openapi_schema::text, NULL
    FROM integration i
    JOIN tool t ON t.id = i.tool_id
    WHERE t.openapi_schema IS NOT NULL
    ORDER BY i.id
"""

# A GraphQL app has api_app_id and no tool_id. The old schema has no kind row
# for it.
_COUNT_GRAPHQL_INTEGRATIONS = """
    SELECT count(*) FROM integration
    WHERE api_app_id IS NOT NULL AND tool_id IS NULL
"""

_LINK_INTEGRATIONS = """
    UPDATE integration i
    SET api_app_id = a.id
    FROM api_app a
    WHERE a.id = i.id
"""

_SET_API_APP_SEQUENCE = """
    SELECT setval(
        pg_get_serial_sequence('api_app', 'id'),
        coalesce((SELECT max(id) FROM api_app), 1),
        (SELECT max(id) FROM api_app) IS NOT NULL
    )
"""


def _index_state(conn: sa.engine.Connection, qualified_name: str) -> bool | None:
    """None when the index does not exist, otherwise pg_index.indisvalid.

    An interrupted concurrent build leaves an invalid index.
    """
    return conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": qualified_name},
    ).scalar_one_or_none()


def _is_lock_timeout(error: DBAPIError) -> bool:
    # psycopg2 and SQLAlchemy's asyncpg adapter both set `pgcode` on the
    # driver error, but the DBAPI error type does not declare it.
    pgcode = getattr(error.orig, "pgcode", None)  # ods: ignore[getattr]
    return pgcode == _LOCK_NOT_AVAILABLE


def _with_bounded_lock_wait(change: Callable[[], None]) -> None:
    """Runs a change with a bounded lock wait, as 730bce2814a0 does.

    An ALTER TABLE on integration waits for the open transactions on it, and
    the chat queries queue behind that wait. A short lock_timeout keeps each
    wait short; each attempt runs in a savepoint, so a timeout retries
    instead of failing the migration.
    """
    bind = op.get_bind()
    for attempt in range(1, _LOCK_ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                change()
            break
        except DBAPIError as e:
            if attempt == _LOCK_ATTEMPTS or not _is_lock_timeout(e):
                raise
            logger.warning(
                "The api_app change timed out waiting for a "
                "lock (attempt %s/%s). Retrying in %ss.",
                attempt,
                _LOCK_ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition, postgresql_not_valid=True)


def _alter_integration() -> None:
    op.add_column("integration", sa.Column("api_app_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        FK_NAME,
        "integration",
        "api_app",
        ["api_app_id"],
        ["id"],
        postgresql_not_valid=True,
    )
    # A REST app keeps both tool_id and api_app_id for one release.
    _replace_check(
        "integration",
        SINGLE_KIND,
        "num_nonnulls(mcp_server_id, external_app_id, "
        "coalesce(tool_id, api_app_id)) = 1",
    )


def _alter_integration_action() -> None:
    _replace_check(
        "integration_action",
        ACTION_SOURCE,
        "source IN ('mcp', 'openapi', 'external_app', 'graphql')",
    )


def _create_api_app_and_copy() -> None:
    op.create_table(
        "api_app",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("api_type", sa.String(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("openapi_document", sa.Text(), nullable=True),
        sa.Column("graphql_schema", sa.Text(), nullable=True),
        # Two writers fill these columns outside the app's validation: the SQL
        # copy in this revision, and for one release the dual write beside
        # the OpenAPI tool row.
        sa.CheckConstraint(
            "(api_type = 'rest' AND openapi_document IS NOT NULL "
            "AND graphql_schema IS NULL) "
            "OR (api_type = 'graphql' AND graphql_schema IS NOT NULL "
            "AND openapi_document IS NULL)",
            name="ck_api_app_definition",
        ),
    )
    op.execute(_COPY_OPENAPI_TOOLS)
    op.execute(_SET_API_APP_SEQUENCE)
    # integration stays locked from the ALTER to the commit, so it is altered
    # last, with only the link after it.
    _with_bounded_lock_wait(_alter_integration_action)
    _with_bounded_lock_wait(_alter_integration)
    op.execute(_LINK_INTEGRATIONS)


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The first phase commits as one unit; the new column identifies a retry.
    if "api_app_id" not in {
        column["name"]
        for column in sa.inspect(bind).get_columns("integration", schema=schema)
    }:
        _create_api_app_and_copy()
    # Release the DDL locks before the concurrent index build.
    # env.py owns the transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        # A plain SET outlives the statement on this pooled connection.
        try:
            _build_index_and_validate(conn, schema)
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def _build_index_and_validate(conn: sa.engine.Connection, schema: str) -> None:
    quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
    qualified_name = f'{quoted_schema}."{INDEX_NAME}"'
    state = _index_state(conn, qualified_name)
    if state is False:
        conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
    if state is not True:
        conn.exec_driver_sql(
            f'CREATE UNIQUE INDEX CONCURRENTLY "{INDEX_NAME}" '
            f"ON {quoted_schema}.integration (api_app_id)"
        )
    for table, constraint in (
        ("integration", FK_NAME),
        ("integration", SINGLE_KIND),
        ("integration_action", ACTION_SOURCE),
    ):
        conn.exec_driver_sql(
            f"ALTER TABLE {quoted_schema}.{table} VALIDATE CONSTRAINT {constraint}"
        )


def _restore_integration_action() -> None:
    _replace_check(
        "integration_action",
        ACTION_SOURCE,
        "source IN ('mcp', 'openapi', 'external_app')",
    )


def _restore_integration() -> None:
    _replace_check(
        "integration",
        SINGLE_KIND,
        "num_nonnulls(mcp_server_id, external_app_id, tool_id) = 1",
    )
    op.drop_index(INDEX_NAME, table_name="integration")
    op.drop_constraint(FK_NAME, "integration", type_="foreignkey")
    op.drop_column("integration", "api_app_id")


def downgrade() -> None:
    graphql_apps: int = (
        op.get_bind().execute(sa.text(_COUNT_GRAPHQL_INTEGRATIONS)).scalar_one()
    )
    if graphql_apps:
        raise RuntimeError(
            f"{graphql_apps} GraphQL app integration(s) exist. The schema before "
            "this revision cannot hold them. An admin must delete the GraphQL "
            "apps before the downgrade."
        )
    # GraphQL apps break the old checks, so they stay unvalidated.
    _with_bounded_lock_wait(_restore_integration_action)
    _with_bounded_lock_wait(_restore_integration)
    op.drop_table("api_app")
