"""add tab_index to tool_call

Revision ID: 4cebcbc9b2ae
Revises: 87c52ec39f84
Create Date: 2025-12-16

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4cebcbc9b2ae"
down_revision = "87c52ec39f84"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "tool_call",
        sa.Column("tab_index", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tool_call", "tab_index")
