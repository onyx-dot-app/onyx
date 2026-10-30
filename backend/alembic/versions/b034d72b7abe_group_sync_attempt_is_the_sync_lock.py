"""group sync attempt is the sync lock

Revision ID: b034d72b7abe
Revises: ee7680aff413
Create Date: 2026-10-13 13:28:48.828832

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b034d72b7abe"
down_revision = "ee7680aff413"
branch_labels = None
depends_on = None

_OPEN = "status IN ('NOT_STARTED', 'IN_PROGRESS')"


def upgrade() -> None:
    op.add_column(
        "external_group_permission_sync_attempt",
        sa.Column("celery_task_id", sa.String(), nullable=True),
    )

    # The unique index needs at most one open attempt per cc_pair. Keep the
    # newest one; the lease reaper handles it if it is abandoned.
    op.execute(
        f"""
        UPDATE external_group_permission_sync_attempt
        SET status = 'FAILED',
            time_finished = now(),
            error_message = 'Abandoned: a newer attempt replaced it'
        WHERE {_OPEN}
          AND connector_credential_pair_id IS NOT NULL
          AND id NOT IN (
              SELECT DISTINCT ON (connector_credential_pair_id) id
              FROM external_group_permission_sync_attempt
              WHERE {_OPEN}
              ORDER BY connector_credential_pair_id, time_created DESC, id DESC
          )
        """
    )
    op.create_index(
        "uq_group_sync_attempt_open_cc_pair",
        "external_group_permission_sync_attempt",
        ["connector_credential_pair_id"],
        unique=True,
        postgresql_where=sa.text(_OPEN),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_group_sync_attempt_open_cc_pair",
        table_name="external_group_permission_sync_attempt",
    )
    op.drop_column("external_group_permission_sync_attempt", "celery_task_id")
