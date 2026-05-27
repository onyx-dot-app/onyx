"""Add include_citations to persona

Revision ID: b3d9f1a2c4e7
Revises: 366c05b6f485
Create Date: 2026-05-27 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b3d9f1a2c4e7"
down_revision = "366c05b6f485"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persona",
        sa.Column(
            "include_citations",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("persona", "include_citations")
