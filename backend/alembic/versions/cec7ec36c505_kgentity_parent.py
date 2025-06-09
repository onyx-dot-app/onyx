"""kgentity_parent

Revision ID: cec7ec36c505
Revises: 495cb26ce93e
Create Date: 2025-06-07 20:07:46.400770

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "cec7ec36c505"
down_revision = "495cb26ce93e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kg_entity",
        sa.Column("parent_key", sa.String(), nullable=True, index=True),
    )
    # NOTE: you will have to reindex the KG after this migration as the parent_key will be null


def downgrade() -> None:
    op.drop_column("kg_entity", "parent_key")
