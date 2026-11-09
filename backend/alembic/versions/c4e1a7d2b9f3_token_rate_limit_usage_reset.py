"""token rate limit usage reset

Revision ID: c4e1a7d2b9f3
Revises: 8673a2d95b1e
Create Date: 2026-11-02 12:00:00.000000

Adds what an admin needs to reset a limit's usage without deleting usage rows:

- usage_reset_at: usage before this time does not count toward the limit's
  current period.
- token_rate_limit_usage_baseline: each user's usage in the reset day's bucket
  at the reset, subtracted from that bucket. A pool limit subtracts the sum
  over the users it covers.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4e1a7d2b9f3"
down_revision = "8673a2d95b1e"
branch_labels = None
depends_on = None

BASELINE_TABLE = "token_rate_limit_usage_baseline"


def upgrade() -> None:
    op.add_column(
        "token_rate_limit",
        sa.Column("usage_reset_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        BASELINE_TABLE,
        sa.Column(
            "token_rate_limit_id",
            sa.Integer(),
            sa.ForeignKey("token_rate_limit.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_cents", sa.Numeric(18, 6), nullable=False),
    )


def downgrade() -> None:
    op.drop_table(BASELINE_TABLE)
    op.drop_column("token_rate_limit", "usage_reset_at")
