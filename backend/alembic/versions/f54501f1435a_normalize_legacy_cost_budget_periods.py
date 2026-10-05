"""normalize legacy cost budget periods

Cost budgets only support daily/weekly/monthly (24/168/720h) periods, but rows
can hold any whole-day period. Enforcement skips unsupported rows, so snap them
to the nearest supported period to keep them active. A row carrying both budgets
shares period_hours, so its token window moves with it.

Revision ID: f54501f1435a
Revises: df90f43d9ab2
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f54501f1435a"
down_revision = "df90f43d9ab2"
branch_labels = None
depends_on = None

DAILY_HOURS = 24
WEEKLY_HOURS = 168
MONTHLY_HOURS = 720
# Each row snaps to its nearest supported period.
DAILY_WEEKLY_MIDPOINT = (DAILY_HOURS + WEEKLY_HOURS) // 2
WEEKLY_MONTHLY_MIDPOINT = (WEEKLY_HOURS + MONTHLY_HOURS) // 2

token_rate_limit_table = sa.table(
    "token_rate_limit",
    sa.column("period_hours", sa.Integer),
    sa.column("cost_budget_cents", sa.Numeric),
)


def upgrade() -> None:
    period = token_rate_limit_table.c.period_hours
    op.execute(
        sa.update(token_rate_limit_table)
        .where(
            token_rate_limit_table.c.cost_budget_cents.is_not(None),
            period.not_in([DAILY_HOURS, WEEKLY_HOURS, MONTHLY_HOURS]),
        )
        .values(
            period_hours=sa.case(
                (period < DAILY_WEEKLY_MIDPOINT, DAILY_HOURS),
                (period < WEEKLY_MONTHLY_MIDPOINT, WEEKLY_HOURS),
                else_=MONTHLY_HOURS,
            )
        )
    )


def downgrade() -> None:
    # Lossy normalization. The original periods cannot be restored.
    pass
