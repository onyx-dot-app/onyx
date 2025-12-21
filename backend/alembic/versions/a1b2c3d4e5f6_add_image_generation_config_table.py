"""add image generation config table

Revision ID: a1b2c3d4e5f6
Revises: e8f0d2a38171
Create Date: 2025-12-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "e8f0d2a38171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_generation_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
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
