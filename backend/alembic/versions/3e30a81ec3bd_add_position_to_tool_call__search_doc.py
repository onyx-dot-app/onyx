"""add position to tool_call__search_doc

The order in which a tool call returned its search docs. Rows written
before this column have no position and keep their old order (by id).

Revision ID: 3e30a81ec3bd
Revises: 3951a74ef078
Create Date: 2026-10-29 15:25:55.658327

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3e30a81ec3bd"
down_revision = "3951a74ef078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_call__search_doc",
        sa.Column("position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_call__search_doc", "position")
