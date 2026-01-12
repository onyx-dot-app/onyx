"""add is_selected to tool_call__search_doc

Revision ID: a1b2c3d4e5f6
Revises: 8405ca81cc83
Create Date: 2026-01-12 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "8405ca81cc83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_call__search_doc",
        sa.Column(
            "is_selected", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_column("tool_call__search_doc", "is_selected")
