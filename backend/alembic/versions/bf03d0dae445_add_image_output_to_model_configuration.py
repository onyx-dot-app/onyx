"""add image output to model_configuration

Revision ID: bf03d0dae445
Revises: e8f0d2a38171
Create Date: 2025-12-04 15:33:38.717504

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "bf03d0dae445"
down_revision = "e8f0d2a38171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configuration",
        sa.Column("supports_image_output", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "supports_image_output")
