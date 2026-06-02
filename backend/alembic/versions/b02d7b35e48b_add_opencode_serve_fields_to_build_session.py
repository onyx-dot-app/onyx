"""Add opencode-serve fields to build_session

Revision ID: b02d7b35e48b
Revises: 7f5b159041be
Create Date: 2026-05-22 11:53:07.677442

Adds ``opencode_session_id`` + ``agent_provider`` + ``agent_model``.
See ``docs/craft/opencode-serve-migration.md``.
"""

from alembic import op
import sqlalchemy as sa


revision = "b02d7b35e48b"
down_revision = "7f5b159041be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build_session",
        sa.Column("opencode_session_id", sa.String(), nullable=True),
    )
    op.add_column(
        "build_session",
        sa.Column("agent_provider", sa.String(), nullable=True),
    )
    op.add_column(
        "build_session",
        sa.Column("agent_model", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("build_session", "agent_model")
    op.drop_column("build_session", "agent_provider")
    op.drop_column("build_session", "opencode_session_id")
