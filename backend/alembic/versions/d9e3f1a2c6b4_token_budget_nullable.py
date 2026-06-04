"""token_budget nullable (cost-only limits)

Revision ID: d9e3f1a2c6b4
Down revision: b8c2d6e4f1a7
"""
from alembic import op
import sqlalchemy as sa

revision = "d9e3f1a2c6b4"
down_revision = "b8c2d6e4f1a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("token_rate_limit", "token_budget", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE token_rate_limit SET token_budget = 0 WHERE token_budget IS NULL")
    op.alter_column("token_rate_limit", "token_budget", nullable=False)
