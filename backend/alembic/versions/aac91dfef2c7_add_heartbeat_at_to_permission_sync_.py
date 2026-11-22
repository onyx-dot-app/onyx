"""add heartbeat_at to permission sync attempts

Revision ID: aac91dfef2c7
Revises: c92b67e56ec4
Create Date: 2026-10-13 13:10:38.273867

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aac91dfef2c7"
down_revision = "c92b67e56ec4"
branch_labels = None
depends_on = None

_TABLES = ("doc_permission_sync_attempt", "external_group_permission_sync_attempt")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )

        # A worker that died mid-sync left its attempt open forever. Fail every
        # open attempt that a newer open attempt for the same cc_pair replaced;
        # the lease reaper handles the newest one.
        op.execute(
            f"""
            UPDATE {table}
            SET status = 'FAILED',
                time_finished = now(),
                error_message = 'Abandoned: a newer attempt replaced it'
            WHERE status IN ('NOT_STARTED', 'IN_PROGRESS')
              AND id NOT IN (
                  SELECT DISTINCT ON (connector_credential_pair_id) id
                  FROM {table}
                  WHERE status IN ('NOT_STARTED', 'IN_PROGRESS')
                  ORDER BY connector_credential_pair_id, time_created DESC, id DESC
              )
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "heartbeat_at")
