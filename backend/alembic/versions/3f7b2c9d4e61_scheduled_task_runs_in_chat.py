"""run scheduled tasks in chat

`scheduled_task_run.chat_session_id` links a run to its hidden chat. Runs no
longer make Craft build sessions, so `scheduled_task_run.session_id` goes.
The migration touches only the small run table, not chat_session.

Revision ID: 3f7b2c9d4e61
Revises: e08a3dc8052a
Create Date: 2026-11-20 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "3f7b2c9d4e61"
down_revision = "e08a3dc8052a"
branch_labels = None
depends_on = None

_INDEX = "ix_scheduled_task_run_chat_session"
_BUILD_SESSION_INDEX = "ix_scheduled_task_run_session"


def upgrade() -> None:
    op.add_column(
        "scheduled_task_run",
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(  # migration-design: allow blocking-index - the run table is small
        _INDEX, "scheduled_task_run", ["chat_session_id"]
    )
    # A Craft run still in flight can no longer finish; without this it would
    # stay in flight and make every later fire of its task SKIPPED.
    op.execute(
        """
        UPDATE scheduled_task_run
        SET status = 'FAILED', error_class = 'stuck',
            error_detail = 'Craft run ended by the move to chat',
            finished_at = now(), version = version + 1
        WHERE status IN ('RUNNING', 'AWAITING_APPROVAL')
        """
    )
    op.drop_index(_BUILD_SESSION_INDEX, table_name="scheduled_task_run")
    op.drop_column("scheduled_task_run", "session_id")


def downgrade() -> None:
    # The older code has no CANCELLED run status.
    op.execute(
        """
        UPDATE scheduled_task_run
        SET status = 'FAILED', error_class = COALESCE(error_class, 'cancelled')
        WHERE status = 'CANCELLED'
        """
    )
    op.add_column(
        "scheduled_task_run",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "scheduled_task_run_session_id_fkey",
        "scheduled_task_run",
        "build_session",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(_BUILD_SESSION_INDEX, "scheduled_task_run", ["session_id"])
    op.drop_index(_INDEX, table_name="scheduled_task_run")
    op.drop_column("scheduled_task_run", "chat_session_id")
