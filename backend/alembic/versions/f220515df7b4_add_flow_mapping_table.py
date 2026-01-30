"""Add flow mapping table

Revision ID: f220515df7b4
Revises: e7f8a9b0c1d2
Create Date: 2026-01-30 12:21:24.955922

"""

from onyx.db.enums import ModelInputModalityType
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f220515df7b4"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "input_modality",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "input_modality_type",
            sa.Enum(
                ModelInputModalityType, name="modelinputmodalitytype", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, default=False),
        sa.Column("model_configuration_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["model_configuration_id"], ["model_configuration.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "input_modality_type",
            "model_configuration_id",
            name="uq_input_modality_input_modality_type_model_configuration",
        ),
    )

    # Partial unique index so that there is at most one default for each flow type
    op.create_index(
        "ix_one_default_per_input_modality",
        "input_modality",
        ["input_modality_type"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )


def downgrade() -> None:
    # Drop the input_modality table (index is dropped automatically with table)
    op.drop_table("input_modality")

    # Drop the enum type if it was created by this migration
    # (only if no other tables reference it)
    op.execute("DROP TYPE IF EXISTS modelinputmodalitytype;")
