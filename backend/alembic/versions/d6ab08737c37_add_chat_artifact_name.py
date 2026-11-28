"""add chat_artifact name

Revision ID: d6ab08737c37
Revises: c2caf6a8285c
Create Date: 2026-11-24 12:00:00.000000

Adds chat_artifact.name, the name that a rename gives the artifact. NULL
means the newest available version's file name.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d6ab08737c37"
down_revision = "c2caf6a8285c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_artifact", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_artifact", "name")
