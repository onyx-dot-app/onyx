"""Add additional retrieval controls to Persona

Revision ID: 50b683a8295c
Revises: 7da0ae5ad583
Create Date: 2023-11-27 17:23:29.668422

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "50b683a8295c"
down_revision = "7da0ae5ad583"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("persona", sa.Column("num_chunks", sa.Integer(), nullable=True))
    op.add_column(
        "persona",
        sa.Column("apply_llm_relevance_filter", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persona", "apply_llm_relevance_filter")
    op.drop_column("persona", "num_chunks")
