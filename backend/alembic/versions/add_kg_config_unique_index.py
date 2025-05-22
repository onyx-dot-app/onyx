"""Add unique index to kg_config

Revision ID: add_kg_config_unique_index
Revises: 495cb26ce93e
Create Date: 2024-03-19 09:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "add_kg_config_unique_index"
down_revision = "495cb26ce93e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add a unique index to support upsert operations
    op.create_index(
        "ix_kg_config_variable_name_unique",
        "kg_config",
        ["kg_variable_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_kg_config_variable_name_unique")
