"""add cache_read_cost_per_mtok to model_cost_override

Revision ID: e1f2a3b4c5d6
Down revision: d9e3f1a2c6b4
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d9e3f1a2c6b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_cost_override",
        sa.Column("cache_read_cost_per_mtok", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_cost_override", "cache_read_cost_per_mtok")
