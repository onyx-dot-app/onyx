"""Add the called tool's display name to tool_call.

Revision ID: 280f03ce19b2
Revises: 26ff9e3664f0
Create Date: 2026-11-12 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "280f03ce19b2"
down_revision = "26ff9e3664f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_call", sa.Column("display_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_call", "display_name")
