"""token rate limit calendar periods

Revision ID: 17798d4e2385
Revises: 1a72785a4e97
Create Date: 2026-10-30 13:00:00.000000

Replaces token_rate_limit.period_hours with a DAILY / WEEKLY / MONTHLY period.
Each row moves to the closest standard period at least as long as its own, with
the same budget, so no limit allows more spend than before:

- up to 1 day -> DAILY; 2-7 days -> WEEKLY; 8-30 days -> MONTHLY
- more than 30 days -> MONTHLY, with both budgets prorated by 30 / days

Token budgets also move from rolling to calendar windows. Enabled rows that now
share (scope, group, period) merge into the lowest id, keeping the smaller value
of each budget.

The downgrade maps each period back to 24 / 168 / 720 hours. It can't restore
merged rows, prorated budgets or the original period lengths.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "17798d4e2385"
down_revision = "1a72785a4e97"
branch_labels = None
depends_on = None

HOURS_PER_DAY = 24
MONTH_DAYS = 30

_DAYS = f"CEIL(period_hours / {HOURS_PER_DAY}.0)"

_SET_PERIODS = f"""
UPDATE token_rate_limit
SET period = CASE
        WHEN {_DAYS} <= 1 THEN 'DAILY'
        WHEN {_DAYS} <= 7 THEN 'WEEKLY'
        ELSE 'MONTHLY'
    END,
    token_budget = CASE
        WHEN {_DAYS} > {MONTH_DAYS} AND token_budget IS NOT NULL
            THEN GREATEST(1, FLOOR(token_budget * {MONTH_DAYS} / {_DAYS}))::integer
        ELSE token_budget
    END,
    cost_budget_cents = CASE
        WHEN {_DAYS} > {MONTH_DAYS}
            THEN cost_budget_cents * {MONTH_DAYS} / {_DAYS}
        ELSE cost_budget_cents
    END
"""

# The API links each group limit to one group; MIN keeps the key well defined
# for any row linked to several.
_LIMIT_KEYS = """
SELECT
    t.id,
    t.scope,
    t.period,
    (
        SELECT MIN(link.user_group_id)
        FROM token_rate_limit__user_group AS link
        WHERE link.rate_limit_id = t.id
    ) AS group_id,
    t.token_budget,
    t.cost_budget_cents
FROM token_rate_limit AS t
WHERE t.enabled
"""

_MERGE_COLLISIONS = f"""
WITH keyed AS ({_LIMIT_KEYS}),
groups AS (
    SELECT
        MIN(id) AS keep_id,
        MIN(token_budget) AS token_budget,
        MIN(cost_budget_cents) AS cost_budget_cents,
        ARRAY_AGG(id) AS ids
    FROM keyed
    GROUP BY scope, period, group_id
    HAVING COUNT(*) > 1
)
UPDATE token_rate_limit AS t
SET token_budget = g.token_budget, cost_budget_cents = g.cost_budget_cents
FROM groups AS g
WHERE t.id = g.keep_id
"""

_MERGED_IDS = f"""
WITH keyed AS ({_LIMIT_KEYS})
SELECT id
FROM (
    SELECT id, MIN(id) OVER (PARTITION BY scope, period, group_id) AS keep_id
    FROM keyed
) AS ranked
WHERE id <> keep_id
"""


def upgrade() -> None:
    op.add_column("token_rate_limit", sa.Column("period", sa.String(), nullable=True))
    op.execute(sa.text(_SET_PERIODS))
    merged_ids = list(op.get_bind().execute(sa.text(_MERGED_IDS)).scalars())
    op.execute(sa.text(_MERGE_COLLISIONS))
    if merged_ids:
        params = {"ids": merged_ids}
        op.get_bind().execute(
            sa.text(
                "DELETE FROM token_rate_limit__user_group "
                "WHERE rate_limit_id = ANY(:ids)"
            ),
            params,
        )
        op.get_bind().execute(
            sa.text("DELETE FROM token_rate_limit WHERE id = ANY(:ids)"), params
        )
    op.alter_column("token_rate_limit", "period", nullable=False)
    op.drop_column("token_rate_limit", "period_hours")


def downgrade() -> None:
    op.add_column(
        "token_rate_limit", sa.Column("period_hours", sa.Integer(), nullable=True)
    )
    op.execute(
        sa.text(
            """
            UPDATE token_rate_limit
            SET period_hours = CASE period
                WHEN 'DAILY' THEN 24
                WHEN 'WEEKLY' THEN 168
                ELSE 720
            END
            """
        )
    )
    op.alter_column("token_rate_limit", "period_hours", nullable=False)
    op.drop_column("token_rate_limit", "period")
