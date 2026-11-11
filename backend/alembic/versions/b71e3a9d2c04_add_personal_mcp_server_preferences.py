"""add personal MCP server preferences

Revision ID: b71e3a9d2c04
Revises: b034d72b7abe
Create Date: 2026-10-15 19:25:16.614907

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b71e3a9d2c04"
down_revision = "b034d72b7abe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_server_user_preference",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled_in_chat",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "enabled_in_craft",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_server.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "mcp_server_id"),
    )


def downgrade() -> None:
    op.drop_table("mcp_server_user_preference")
