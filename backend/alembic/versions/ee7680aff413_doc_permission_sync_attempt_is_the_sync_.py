"""doc permission sync attempt is the sync lock

Revision ID: ee7680aff413
Revises: 6f888c8ff904
Create Date: 2026-10-13 13:21:02.471577

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ee7680aff413"
down_revision = "6f888c8ff904"
branch_labels = None
depends_on = None

_OPEN = "status IN ('NOT_STARTED', 'IN_PROGRESS')"


def upgrade() -> None:
    op.add_column(
        "doc_permission_sync_attempt",
        sa.Column("celery_task_id", sa.String(), nullable=True),
    )

    # The unique index needs at most one open attempt per cc_pair. Keep the
    # newest one; the lease reaper handles it if it is abandoned.
    op.execute(
        f"""
        UPDATE doc_permission_sync_attempt
        SET status = 'FAILED',
            time_finished = now(),
            error_message = 'Abandoned: a newer attempt replaced it'
        WHERE {_OPEN}
          AND id NOT IN (
              SELECT DISTINCT ON (connector_credential_pair_id) id
              FROM doc_permission_sync_attempt
              WHERE {_OPEN}
              ORDER BY connector_credential_pair_id, time_created DESC, id DESC
          )
        """
    )
    op.create_index(
        "uq_doc_permission_sync_attempt_open_cc_pair",
        "doc_permission_sync_attempt",
        ["connector_credential_pair_id"],
        unique=True,
        postgresql_where=sa.text(_OPEN),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_doc_permission_sync_attempt_open_cc_pair",
        table_name="doc_permission_sync_attempt",
    )
    op.drop_column("doc_permission_sync_attempt", "celery_task_id")
