"""add personal OpenAPI preferences

Revision ID: c82f4a0e3d15
Revises: b71e3a9d2c04
"""

from alembic import op
import sqlalchemy as sa

revision = "c82f4a0e3d15"
down_revision = "b71e3a9d2c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_user_preference",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled_in_chat",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tool.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tool_id"),
    )


def downgrade() -> None:
    op.drop_table("tool_user_preference")
