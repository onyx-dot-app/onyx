"""Add display_name to model_configuration

Revision ID: 7bd55f264e1b
Revises: e8f0d2a38171
Create Date: 2025-12-04

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7bd55f264e1b"
down_revision = "e8f0d2a38171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configuration",
        sa.Column("display_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "display_name")
