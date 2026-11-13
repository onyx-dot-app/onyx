"""add resolution to index_attempt_errors

Records how an index attempt error closed (retry, later_run, without_retry),
which run closed it and when. Existing rows keep nulls, except open rows filed
by the time an admin resolved their run before this revision: they close as
without_retry at that resolution, so the run stays resolved.

Revision ID: f9f6abda4011
Revises: c4e1a7d2b9f3
Create Date: 2026-11-02 19:00:00.000000

index_attempt_errors can be large, so the index on the closing run is built
CONCURRENTLY: commit the migration transaction, then build on a dedicated
AUTOCOMMIT connection. That connection does not get the migration connection's
search_path, so the operations name the schema. The FK is added valid: its
check scans index_attempt_errors under ADD COLUMN's lock, measured at 95 ms on
3M rows, and a NOT VALID add would need a raw VALIDATE CONSTRAINT.
"""

from collections.abc import Callable

from alembic import op
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from onyx.db.enums import CCPairRunKind, IndexAttemptErrorResolvedReason


# revision identifiers, used by Alembic.
revision = "f9f6abda4011"
down_revision = "c4e1a7d2b9f3"
branch_labels = None
depends_on = None

_TABLE = "index_attempt_errors"
_COLUMN = "resolved_by_index_attempt_id"
_INDEX_NAME = "ix_index_attempt_errors_resolved_by_index_attempt_id"


def _index_state(conn: sa.engine.Connection, schema: str) -> bool | None:
    """None if the index does not exist, else pg_index.indisvalid. A failed
    concurrent build leaves an INVALID index."""
    pg_index: sa.TableClause = sa.table(
        "pg_index",
        sa.column("indexrelid"),
        sa.column("indisvalid"),
        schema="pg_catalog",
    )
    quote: Callable[[str], str] = conn.dialect.identifier_preparer.quote
    return conn.execute(
        sa.select(pg_index.c.indisvalid).where(
            pg_index.c.indexrelid
            == sa.func.to_regclass(f"{quote(schema)}.{quote(_INDEX_NAME)}")
        )
    ).scalar_one_or_none()


def _release_migration_snapshot() -> tuple[sa.engine.Connection, str]:
    """Commits the migration transaction and returns (bind, its schema)."""
    bind: sa.engine.Connection = op.get_bind()
    schema: str = bind.execute(sa.select(sa.func.current_schema())).scalar_one()
    bind.commit()
    return bind, schema


def _drop_index_concurrently(ops: Operations, schema: str) -> None:
    ops.drop_index(
        _INDEX_NAME,
        table_name=_TABLE,
        schema=schema,
        postgresql_concurrently=True,
    )


def _close_errors_under_resolved_runs() -> None:
    errors: sa.TableClause = sa.table(
        _TABLE,
        sa.column("index_attempt_id"),
        sa.column("is_resolved"),
        sa.column("resolved_reason"),
        sa.column("resolved_at"),
        sa.column("time_created"),
    )
    resolutions: sa.TableClause = sa.table(
        "cc_pair_run_resolution",
        sa.column("run_kind"),
        sa.column("attempt_id"),
        sa.column("resolved_at"),
    )
    op.execute(
        sa.update(errors)
        .where(
            resolutions.c.run_kind == CCPairRunKind.INDEXING.value,
            resolutions.c.attempt_id == errors.c.index_attempt_id,
            ~errors.c.is_resolved,
            errors.c.resolved_reason.is_(None),
            # Filed after the resolution, the error reopens the run.
            errors.c.time_created <= resolutions.c.resolved_at,
        )
        .values(
            resolved_reason=IndexAttemptErrorResolvedReason.WITHOUT_RETRY.value,
            resolved_at=resolutions.c.resolved_at,
        )
    )


def upgrade() -> None:
    # The index build runs after the columns commit, so a failed build leaves
    # them in place with the revision unstamped, and the rerun skips them.
    existing: set[str] = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)
    }
    for column in (
        sa.Column(
            "resolved_reason",
            sa.Enum(
                IndexAttemptErrorResolvedReason,
                native_enum=False,
                values_callable=lambda x: [e.value for e in x],
            ),
            nullable=True,
        ),
        sa.Column(
            _COLUMN,
            sa.Integer(),
            sa.ForeignKey("index_attempt.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in existing:
            op.add_column(_TABLE, column)
    _close_errors_under_resolved_runs()

    bind, schema = _release_migration_snapshot()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        state: bool | None = _index_state(conn, schema)
        if state is True:
            return
        ops: Operations = Operations(MigrationContext.configure(conn))
        if state is False:
            _drop_index_concurrently(ops, schema)
        ops.create_index(
            _INDEX_NAME,
            _TABLE,
            [_COLUMN],
            schema=schema,
            postgresql_where=sa.column(_COLUMN).is_not(None),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if _index_state(conn, schema) is not None:
            _drop_index_concurrently(
                Operations(MigrationContext.configure(conn)), schema
            )

    op.drop_column(_TABLE, "resolved_at")
    op.drop_column(_TABLE, _COLUMN)
    op.drop_column(_TABLE, "resolved_reason")
