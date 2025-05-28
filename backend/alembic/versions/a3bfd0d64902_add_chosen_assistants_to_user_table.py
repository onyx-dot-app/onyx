"""Add chosen_assistants to User table

Revision ID: a3bfd0d64902
Revises: ec85f2b3c544
Create Date: 2024-05-26 17:22:24.834741

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a3bfd0d64902"
down_revision = "ec85f2b3c544"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("chosen_assistants", postgresql.ARRAY(sa.Integer()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "chosen_assistants")
