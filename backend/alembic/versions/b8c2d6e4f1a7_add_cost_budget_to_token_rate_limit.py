"""add cost_budget_cents to token_rate_limit

Revision ID: b8c2d6e4f1a7
Revises: a7f3e2c1b9d4
Create Date: 2026-06-03 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b8c2d6e4f1a7"
down_revision = "a7f3e2c1b9d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "token_rate_limit",
        sa.Column("cost_budget_cents", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("token_rate_limit", "cost_budget_cents")
