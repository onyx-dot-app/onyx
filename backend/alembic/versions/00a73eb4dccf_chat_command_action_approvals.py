"""chat command action approvals

Revision ID: 00a73eb4dccf
Revises: d04326aae2f9
Create Date: 2026-11-24 10:00:00.000000

An action_approval row can belong to a command that a chat runs in its VM:
session_id becomes nullable, and chat_session_id and command_id are added.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "00a73eb4dccf"
down_revision = "d04326aae2f9"
branch_labels = None
depends_on = None

FK_NAME = "fk_action_approval_chat_session_id"
INDEX_NAME = "ix_action_approval_chat_command"


def upgrade() -> None:
    op.alter_column(
        "action_approval",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "action_approval",
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "action_approval",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Every existing row has no chat_session_id, so validation checks nothing.
    op.create_foreign_key(
        FK_NAME,
        "action_approval",
        "chat_session",
        ["chat_session_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.create_index(
        # migration-design: allow blocking-index - action_approval holds short-lived approval rows and is small
        INDEX_NAME,
        "action_approval",
        ["chat_session_id", "command_id"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM action_approval WHERE session_id IS NULL")
    op.drop_index(INDEX_NAME, table_name="action_approval")
    op.drop_constraint(FK_NAME, "action_approval", type_="foreignkey")
    op.drop_column("action_approval", "command_id")
    op.drop_column("action_approval", "chat_session_id")
    op.alter_column(
        "action_approval",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
