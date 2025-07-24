"""remove kg subtype from db

Revision ID: 65bc6e0f8500
Revises: cec7ec36c505
Create Date: 2025-06-13 10:04:27.705976

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "65bc6e0f8500"
down_revision = "cec7ec36c505"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("kg_entity", "entity_class")
    op.drop_column("kg_entity", "entity_subtype")
    op.drop_column("kg_entity_extraction_staging", "entity_class")
    op.drop_column("kg_entity_extraction_staging", "entity_subtype")


def downgrade() -> None:
    op.add_column(
        "kg_entity_extraction_staging",
        sa.Column("entity_subtype", sa.String(), nullable=True, index=True),
    )
    op.add_column(
        "kg_entity_extraction_staging",
        sa.Column("entity_class", sa.String(), nullable=True, index=True),
    )
    op.add_column(
        "kg_entity", sa.Column("entity_subtype", sa.String(), nullable=True, index=True)
    )
    op.add_column(
        "kg_entity", sa.Column("entity_class", sa.String(), nullable=True, index=True)
    )
