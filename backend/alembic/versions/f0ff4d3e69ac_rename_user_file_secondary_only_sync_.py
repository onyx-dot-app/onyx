"""rename user_file secondary_only_sync_pending to secondary_reconcile_pending

Revision ID: f0ff4d3e69ac
Revises: e3e324f5d32c
Create Date: 2026-07-09 15:32:03.179317

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "f0ff4d3e69ac"
down_revision = "e3e324f5d32c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The user-file flag covers content too (not just an ACL "sync"), so name it for the
    # reconcile. RENAME COLUMN carries the partial index predicate; rename the index to match.
    # Metadata-only renames — no rewrite, no CONCURRENTLY.
    op.execute(
        "ALTER TABLE user_file "
        "RENAME COLUMN secondary_only_sync_pending TO secondary_reconcile_pending"
    )
    op.execute(
        "ALTER INDEX ix_user_file_secondary_only_sync_pending "
        "RENAME TO ix_user_file_secondary_reconcile_pending"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX ix_user_file_secondary_reconcile_pending "
        "RENAME TO ix_user_file_secondary_only_sync_pending"
    )
    op.execute(
        "ALTER TABLE user_file "
        "RENAME COLUMN secondary_reconcile_pending TO secondary_only_sync_pending"
    )
