"""key usage dedup indexes by model configuration

Revision ID: 1a72785a4e97
Revises: 0437efc9ed01
Create Date: 2026-10-30 12:05:00.000000

Adds COALESCE(model_configuration_id, 0) to uq_user_usage_dims and
uq_system_usage_dims, so two configurations sharing (model, provider) roll up
into separate rows. COALESCE because Postgres before 15 has no NULLS NOT
DISTINCT; the upserts name the same expression as their conflict target.

user_usage takes a write on every LLM call, so each index is rebuilt
CONCURRENTLY under a temporary name, the old one dropped and the new one
renamed. CONCURRENTLY can't run in a transaction, and this project's env.py
makes autocommit_block() unusable (see e0ea2ae62e51), so the migration commits
its transaction and runs the DDL on a dedicated AUTOCOMMIT connection,
schema-qualified from the migration connection's current_schema(). Every step
checks the index state first, so a failed run can be rerun.
"""

import logging
import time

import asyncpg.exceptions
import psycopg2.errors
from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from pydantic import BaseModel


# revision identifiers, used by Alembic.
revision = "1a72785a4e97"
down_revision = "0437efc9ed01"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

MODEL_KEY = "COALESCE(model_configuration_id, 0)"
TEMP_SUFFIX = "_swap"

# CONCURRENTLY waits on every older transaction in the database, whatever schema
# it runs in. A bounded wait fails naming the schema instead of hanging the run.
LOCK_TIMEOUT = "60s"
MAX_ATTEMPTS = 10
RETRY_DELAY_SEC = 5


class _DedupIndex(BaseModel):
    name: str
    columns: str
    predicate: str


_USER_COLUMNS = "user_id, window_start, model, flow, provider, incognito"
_SYSTEM_COLUMNS = "system_attribution, window_start, model, flow, provider"

NEW_INDEXES = [
    _DedupIndex(
        name="uq_user_usage_dims",
        columns=f"{_USER_COLUMNS}, {MODEL_KEY}",
        predicate="actor_kind = 'USER'",
    ),
    _DedupIndex(
        name="uq_system_usage_dims",
        columns=f"{_SYSTEM_COLUMNS}, {MODEL_KEY}",
        predicate="actor_kind = 'SYSTEM'",
    ),
]
OLD_INDEXES = [
    _DedupIndex(
        name="uq_user_usage_dims",
        columns=_USER_COLUMNS,
        predicate="actor_kind = 'USER'",
    ),
    _DedupIndex(
        name="uq_system_usage_dims",
        columns=_SYSTEM_COLUMNS,
        predicate="actor_kind = 'SYSTEM'",
    ),
]

# Rows that differ only by model_configuration_id collide on the old indexes;
# fold each group into its lowest id before rebuilding them.
_MERGE_SPLIT_ROWS = """
WITH groups AS (
    SELECT
        MIN(id) AS keep_id,
        SUM(input_tokens) AS input_tokens,
        SUM(output_tokens) AS output_tokens,
        SUM(cache_read_tokens) AS cache_read_tokens,
        SUM(cache_creation_tokens) AS cache_creation_tokens,
        SUM(cost_cents) AS cost_cents,
        ARRAY_AGG(id) AS ids
    FROM user_usage
    GROUP BY actor_kind, user_id, system_attribution, window_start, model, flow,
        provider, incognito
    HAVING COUNT(*) > 1
),
merged AS (
    UPDATE user_usage AS u
    SET input_tokens = g.input_tokens,
        output_tokens = g.output_tokens,
        cache_read_tokens = g.cache_read_tokens,
        cache_creation_tokens = g.cache_creation_tokens,
        cost_cents = g.cost_cents
    FROM groups AS g
    WHERE u.id = g.keep_id
)
DELETE FROM user_usage AS u
USING groups AS g
WHERE u.id = ANY(g.ids) AND u.id <> g.keep_id
"""


def _index_def(conn: sa.engine.Connection, schema: str, name: str) -> str | None:
    """pg_get_indexdef of a valid index, or None. Drops an INVALID leftover of a
    failed CONCURRENTLY build, which an existence check would mistake for done."""
    row = conn.execute(
        sa.text(
            "SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": f'"{schema}"."{name}"'},
    ).one_or_none()
    if row is None:
        return None
    is_valid, definition = row
    if not is_valid:
        _run(conn, schema, f'DROP INDEX CONCURRENTLY "{schema}"."{name}"')
        return None
    return definition


def _is_lock_timeout(e: DBAPIError) -> bool:
    # Deployed runs use asyncpg, whose SQLAlchemy adapter raises its own error
    # from the driver's. Migration tests run on a sync psycopg2 engine.
    cause: BaseException | None = e.orig.__cause__ if e.orig is not None else None
    return isinstance(cause, asyncpg.exceptions.LockNotAvailableError) or isinstance(
        e.orig, psycopg2.errors.LockNotAvailable
    )


def _run(conn: sa.engine.Connection, schema: str, statement: str) -> None:
    """Runs one DDL statement, retrying while another transaction outlasts
    lock_timeout."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            conn.exec_driver_sql(statement)
            return
        except DBAPIError as e:
            if not _is_lock_timeout(e):
                raise
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"user_usage on {schema}: another transaction blocked "
                    f"{statement!r} for {MAX_ATTEMPTS} attempts of {LOCK_TIMEOUT}. "
                    "End that transaction and rerun the migration"
                ) from e
            logger.warning(
                "user_usage on %s: blocked by another transaction, attempt %d/%d",
                schema,
                attempt,
                MAX_ATTEMPTS,
            )
            time.sleep(RETRY_DELAY_SEC)


def _has_model_key(definition: str) -> bool:
    return "model_configuration_id" in definition


def _swap_index(
    conn: sa.engine.Connection, schema: str, index: _DedupIndex, want_model_key: bool
) -> None:
    temp_name = f"{index.name}{TEMP_SUFFIX}"
    current = _index_def(conn, schema, index.name)
    if current is not None and _has_model_key(current) == want_model_key:
        if _index_def(conn, schema, temp_name) is not None:
            _run(conn, schema, f'DROP INDEX CONCURRENTLY "{schema}"."{temp_name}"')
        return

    if _index_def(conn, schema, temp_name) is None:
        _run(
            conn,
            schema,
            f'CREATE UNIQUE INDEX CONCURRENTLY "{temp_name}" '
            f'ON "{schema}".user_usage ({index.columns}) WHERE {index.predicate}',
        )
    if current is not None:
        _run(conn, schema, f'DROP INDEX CONCURRENTLY "{schema}"."{index.name}"')
    _run(
        conn,
        schema,
        f'ALTER INDEX "{schema}"."{temp_name}" RENAME TO "{index.name}"',
    )


def _release_migration_snapshot() -> tuple[sa.engine.Connection, str]:
    """Commit the migration txn and return (bind, current tenant schema)."""
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The next statement autobegins a transaction, which env.py starts with
    # the tenant search_path; env.py commits it at the end of the schema's run.
    bind.commit()
    return bind, schema


def _swap_all(
    bind: sa.engine.Connection,
    schema: str,
    indexes: list[_DedupIndex],
    want_model_key: bool,
) -> None:
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        # The plain SET outlives the transaction on this connection. Reset it so a
        # pooled connection does not carry the timeout to its next user.
        try:
            for index in indexes:
                _swap_index(conn, schema, index, want_model_key)
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def upgrade() -> None:
    bind, schema = _release_migration_snapshot()
    _swap_all(bind, schema, NEW_INDEXES, want_model_key=True)


def downgrade() -> None:
    op.execute(sa.text(_MERGE_SPLIT_ROWS))
    bind, schema = _release_migration_snapshot()
    _swap_all(bind, schema, OLD_INDEXES, want_model_key=False)
