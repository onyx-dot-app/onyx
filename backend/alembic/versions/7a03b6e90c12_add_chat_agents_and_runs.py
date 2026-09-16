"""Store session agents and individual runs.

Revision ID: 7a03b6e90c12
Revises: ad99acb9be41
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7a03b6e90c12"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("response_rendering", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "chat_session_agent",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_agent_id",
            sa.String(),
            sa.ForeignKey("chat_session_agent.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "creation_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "restoration_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_chat_session_agent_chat_session_id",
        "chat_session_agent",
        ["chat_session_id"],
    )
    op.create_index(
        "ix_chat_session_agent_parent_agent_id",
        "chat_session_agent",
        ["parent_agent_id"],
    )
    op.create_index(
        "ix_chat_session_agent_creation_message_id",
        "chat_session_agent",
        ["creation_message_id"],
    )
    op.create_index(
        "uq_chat_session_agent_root",
        "chat_session_agent",
        ["chat_session_id"],
        unique=True,
        postgresql_where=sa.text("parent_agent_id IS NULL"),
    )
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(),
            sa.ForeignKey("chat_session_agent.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "previous_run_id",
            sa.String(),
            sa.ForeignKey("agent_run.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_run_id",
            sa.String(),
            sa.ForeignKey("agent_run.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("parent_tool_call_id", sa.String(), nullable=True),
        sa.Column("parent_message_id", sa.String(), nullable=True),
        sa.Column("run_index", sa.Integer(), nullable=False),
        sa.Column("transcript", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_agent_run_agent_id", "agent_run", ["agent_id"])
    op.create_index("ix_agent_run_parent_run_id", "agent_run", ["parent_run_id"])
    op.create_index("ix_agent_run_previous_run_id", "agent_run", ["previous_run_id"])
    op.create_index("ix_agent_run_chat_message_id", "agent_run", ["chat_message_id"])


def downgrade() -> None:
    op.drop_table("agent_run")
    op.drop_table("chat_session_agent")
    op.drop_column("chat_message", "response_rendering")
