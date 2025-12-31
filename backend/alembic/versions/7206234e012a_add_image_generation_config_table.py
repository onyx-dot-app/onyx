"""add image generation config table

Revision ID: 7206234e012a
Revises: 699221885109
Create Date: 2025-12-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7206234e012a"
down_revision = "699221885109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_generation_config",
        sa.Column("image_provider_id", sa.String(), primary_key=True),
        sa.Column("model_configuration_id", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_configuration_id"],
            ["model_configuration.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_image_generation_config_is_default",
        "image_generation_config",
        ["is_default"],
        unique=False,
    )
    op.create_index(
        "ix_image_generation_config_model_configuration_id",
        "image_generation_config",
        ["model_configuration_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_image_generation_config_model_configuration_id",
        table_name="image_generation_config",
    )
    op.drop_index(
        "ix_image_generation_config_is_default", table_name="image_generation_config"
    )
    op.drop_table("image_generation_config")
