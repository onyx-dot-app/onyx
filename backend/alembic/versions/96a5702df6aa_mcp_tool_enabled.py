"""mcp_tool_enabled

Revision ID: 96a5702df6aa
Revises: 40926a4dab77
Create Date: 2025-10-09 12:10:21.733097

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "96a5702df6aa"
down_revision = "40926a4dab77"
branch_labels = None
depends_on = None


DELETE_DISABLED_TOOLS_SQL = "DELETE FROM tool WHERE enabled = false"


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_index(
        "ix_tool_mcp_server_enabled",
        "tool",
        ["mcp_server_id", "enabled"],
    )
    # Remove the server default so application controls defaulting
    op.alter_column("tool", "enabled", server_default=None)


def downgrade() -> None:
    op.execute(DELETE_DISABLED_TOOLS_SQL)
    op.drop_index("ix_tool_mcp_server_enabled", table_name="tool")
    op.drop_column("tool", "enabled")
