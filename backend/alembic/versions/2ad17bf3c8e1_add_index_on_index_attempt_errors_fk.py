"""add index on index_attempt_errors.index_attempt_id

Revision ID: 2ad17bf3c8e1
Revises: 631fd2504136
Create Date: 2026-02-19 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2ad17bf3c8e1"
down_revision = "631fd2504136"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_index_attempt_errors_index_attempt_id"
TABLE_NAME = "index_attempt_errors"


def upgrade() -> None:
    # Run concurrently so large tables do not block writes during deployment.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            f"ON {TABLE_NAME} (index_attempt_id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
