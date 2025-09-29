"""Add image input support to model config

Revision ID: 64bd5677aeb6
Revises: 2b75d0a8ffcb
Create Date: 2025-09-28 15:48:12.003612

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "64bd5677aeb6"
down_revision = "2b75d0a8ffcb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configuration",
        sa.Column("supports_image_input", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "supports_image_input")
