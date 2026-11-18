"""Add integration foreign key indexes.

Revision ID: a8c912e4f673
Revises: 730bce2814a0
"""

from alembic import op
import sqlalchemy as sa

revision = "a8c912e4f673"
down_revision = "730bce2814a0"
branch_labels = None
depends_on = None

_INDEXES = (
    ("integration_connection", "integration_id"),
    ("integration_action_policy", "integration_id"),
    ("integration", "created_by_user_id"),
)


def _release_migration_snapshot() -> tuple[sa.engine.Connection, str]:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    bind.commit()
    return bind, schema


def upgrade() -> None:
    bind, schema = _release_migration_snapshot()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
        for table, column in _INDEXES:
            name = f"ix_{table}_{column}"
            qualified_name = f'{quoted_schema}."{name}"'
            valid = conn.execute(
                sa.text(
                    "SELECT indisvalid FROM pg_index "
                    "WHERE indexrelid = to_regclass(:name)"
                ),
                {"name": qualified_name},
            ).scalar_one_or_none()
            if valid is True:
                continue
            if valid is False:
                conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
            conn.exec_driver_sql(
                f'CREATE INDEX CONCURRENTLY "{name}" '
                f'ON {quoted_schema}."{table}" ("{column}")'
            )


def downgrade() -> None:
    bind, schema = _release_migration_snapshot()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
        for table, column in reversed(_INDEXES):
            conn.exec_driver_sql(
                f'DROP INDEX CONCURRENTLY IF EXISTS {quoted_schema}."ix_{table}_{column}"'
            )
