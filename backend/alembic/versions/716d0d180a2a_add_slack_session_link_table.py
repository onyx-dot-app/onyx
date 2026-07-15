"""add slack_session_link table

Revision ID: 716d0d180a2a
Revises: bd38e2a494ff
Create Date: 2026-07-15 11:35:03.737280

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "716d0d180a2a"
down_revision = "bd38e2a494ff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_session_link",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("slack_team_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("thread_ts", sa.String(), nullable=False),
        sa.Column(
            "build_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["build_session_id"], ["build_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "slack_team_id",
            "channel_id",
            "thread_ts",
            name="uq_slack_session_link_thread",
        ),
        sa.UniqueConstraint(
            "build_session_id", name="uq_slack_session_link_build_session_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("slack_session_link")
