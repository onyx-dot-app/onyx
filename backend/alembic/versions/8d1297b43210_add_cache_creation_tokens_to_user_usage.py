"""add cache creation tokens to user usage

Revision ID: 8d1297b43210
Revises: 3350a25df58e
Create Date: 2026-07-31 15:45:02.165673

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8d1297b43210"
down_revision = "3350a25df58e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_usage",
        sa.Column(
            "cache_creation_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_usage", "cache_creation_tokens")
