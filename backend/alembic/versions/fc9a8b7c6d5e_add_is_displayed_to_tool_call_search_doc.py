"""add is_displayed to tool_call__search_doc

Revision ID: fc9a8b7c6d5e
Revises: 41fa44bef321
Create Date: 2026-01-21 10:40:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "fc9a8b7c6d5e"
down_revision = "41fa44bef321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_call__search_doc",
        sa.Column(
            "is_displayed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tool_call__search_doc", "is_displayed")
