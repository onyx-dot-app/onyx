"""Add skill validity classification.

Revision ID: d396075958bd
Revises: b7e9a3c1d2f4
Create Date: 2026-07-16 12:18:01.871231

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d396075958bd"
down_revision = "b7e9a3c1d2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill",
        sa.Column("is_valid", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE skill SET is_valid = true WHERE built_in_skill_id IS NOT NULL")


def downgrade() -> None:
    op.drop_column("skill", "is_valid")
