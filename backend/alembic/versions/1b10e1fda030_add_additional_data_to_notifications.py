"""add additional data to notifications

Revision ID: 1b10e1fda030
Revises: 6756efa39ada
Create Date: 2024-10-15 19:26:44.071259

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "1b10e1fda030"
down_revision = "6756efa39ada"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification", sa.Column("additional_data", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notification", "additional_data")
