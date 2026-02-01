"""Persona new default model configuration id column

Revision ID: be87a654d5af
Revises: e7f8a9b0c1d2
Create Date: 2026-01-30 11:14:17.306275

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "be87a654d5af"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persona",
        sa.Column("default_model_configuration_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_persona_default_model_configuration_id",
        "persona",
        "model_configuration",
        ["default_model_configuration_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_persona_default_model_configuration_id", "persona", type_="foreignkey"
    )

    op.drop_column("persona", "default_model_configuration_id")
