"""token rate limit kinds and models

Revision ID: 8673a2d95b1e
Revises: 17798d4e2385
Create Date: 2026-10-30 14:00:00.000000

Adds what a spending limit needs beyond a workspace or group pool:

- user_group_id on the row replaces token_rate_limit__user_group. The API
  links each limit to one group; a row linked to several becomes one row per
  group. Group rows with no link enforced nothing and are deleted.
- model_configuration_id: NULL counts usage of every model.
- action: BLOCK, or ALERT_ONLY, which nothing reads yet.
- threshold_percent: an ALERT_ONLY row's percentage of the BLOCK value.
- scope widens for USER_GROUP_MEMBER, a per-member group allowance.

A unique index allows one enabled row per (scope, group, model, period,
action, threshold). Enabled rows that already collide merge into the lowest id,
keeping the smaller value of each budget.

The downgrade deletes per-member, model and alert-only rows, which the old
schema can't hold, and restores the link table.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8673a2d95b1e"
down_revision = "17798d4e2385"
branch_labels = None
depends_on = None

LINK_TABLE = "token_rate_limit__user_group"
BUCKET_INDEX = "uq_token_rate_limit_bucket"
BUDGET_CHECK = "ck_token_rate_limit_budget_set"
THRESHOLD_CHECK = "ck_token_rate_limit_threshold"
GROUP_CHECK = "ck_token_rate_limit_group"
OLD_SCOPE_LENGTH = 10

_SPLIT_MULTI_GROUP_ROWS = f"""
INSERT INTO token_rate_limit (
    enabled, token_budget, cost_budget_cents, period, scope, created_at,
    user_group_id
)
SELECT
    t.enabled, t.token_budget, t.cost_budget_cents, t.period, t.scope,
    t.created_at, link.user_group_id
FROM {LINK_TABLE} AS link
JOIN token_rate_limit AS t ON t.id = link.rate_limit_id
WHERE link.user_group_id <> t.user_group_id
"""

_MERGE_COLLISIONS = """
WITH groups AS (
    SELECT
        MIN(id) AS keep_id,
        MIN(token_budget) AS token_budget,
        MIN(cost_budget_cents) AS cost_budget_cents
    FROM token_rate_limit
    WHERE enabled
    GROUP BY scope, user_group_id, period
    HAVING COUNT(*) > 1
)
UPDATE token_rate_limit AS t
SET token_budget = g.token_budget, cost_budget_cents = g.cost_budget_cents
FROM groups AS g
WHERE t.id = g.keep_id
"""

_DELETE_MERGED = """
DELETE FROM token_rate_limit
WHERE id IN (
    SELECT id
    FROM (
        SELECT
            id,
            MIN(id) OVER (PARTITION BY scope, user_group_id, period) AS keep_id
        FROM token_rate_limit
        WHERE enabled
    ) AS ranked
    WHERE id <> keep_id
)
"""


def upgrade() -> None:
    op.alter_column(
        "token_rate_limit",
        "scope",
        type_=sa.String(),
        existing_type=sa.String(length=OLD_SCOPE_LENGTH),
    )
    op.add_column(
        "token_rate_limit",
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "token_rate_limit",
        sa.Column(
            "model_configuration_id",
            sa.Integer(),
            sa.ForeignKey("model_configuration.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "token_rate_limit",
        sa.Column("action", sa.String(), nullable=False, server_default="BLOCK"),
    )
    op.add_column(
        "token_rate_limit",
        sa.Column("threshold_percent", sa.Integer(), nullable=True),
    )

    op.execute(
        sa.text(
            f"""
            UPDATE token_rate_limit AS t
            SET user_group_id = (
                SELECT MIN(link.user_group_id)
                FROM {LINK_TABLE} AS link
                WHERE link.rate_limit_id = t.id
            )
            WHERE t.scope = 'USER_GROUP'
            """
        )
    )
    # Copies of existing rows, not seeded data.
    op.execute(sa.text(_SPLIT_MULTI_GROUP_ROWS))  # migration-determinism: allow
    op.execute(
        sa.text(
            "DELETE FROM token_rate_limit "
            "WHERE scope = 'USER_GROUP' AND user_group_id IS NULL"
        )
    )
    op.drop_table(LINK_TABLE)

    op.execute(sa.text(_MERGE_COLLISIONS))
    op.execute(sa.text(_DELETE_MERGED))

    op.drop_constraint(BUDGET_CHECK, "token_rate_limit", type_="check")
    op.create_check_constraint(
        BUDGET_CHECK,
        "token_rate_limit",
        "token_budget IS NOT NULL OR cost_budget_cents IS NOT NULL "
        "OR threshold_percent IS NOT NULL",
    )
    op.create_check_constraint(
        THRESHOLD_CHECK,
        "token_rate_limit",
        "threshold_percent IS NULL OR (action = 'ALERT_ONLY' "
        "AND token_budget IS NULL AND cost_budget_cents IS NULL "
        "AND threshold_percent BETWEEN 1 AND 100)",
    )
    op.create_check_constraint(
        GROUP_CHECK,
        "token_rate_limit",
        "(scope IN ('USER_GROUP', 'USER_GROUP_MEMBER')) = (user_group_id IS NOT NULL)",
    )
    op.create_index(
        BUCKET_INDEX,
        "token_rate_limit",
        [
            "scope",
            sa.text("COALESCE(user_group_id, 0)"),
            sa.text("COALESCE(model_configuration_id, 0)"),
            "period",
            "action",
            sa.text("COALESCE(threshold_percent, 0)"),
        ],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM token_rate_limit WHERE scope = 'USER_GROUP_MEMBER' "
            "OR model_configuration_id IS NOT NULL OR action <> 'BLOCK'"
        )
    )
    op.drop_index(BUCKET_INDEX, table_name="token_rate_limit")
    op.drop_constraint(GROUP_CHECK, "token_rate_limit", type_="check")
    op.drop_constraint(THRESHOLD_CHECK, "token_rate_limit", type_="check")
    op.drop_constraint(BUDGET_CHECK, "token_rate_limit", type_="check")
    op.create_check_constraint(
        BUDGET_CHECK,
        "token_rate_limit",
        "token_budget IS NOT NULL OR cost_budget_cents IS NOT NULL",
    )

    op.create_table(
        LINK_TABLE,
        sa.Column(
            "rate_limit_id",
            sa.Integer(),
            sa.ForeignKey("token_rate_limit.id"),
            primary_key=True,
        ),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id"),
            primary_key=True,
        ),
    )
    op.execute(
        sa.text(
            f"INSERT INTO {LINK_TABLE} (rate_limit_id, user_group_id) "
            "SELECT id, user_group_id FROM token_rate_limit "
            "WHERE user_group_id IS NOT NULL"
        )
    )

    op.drop_column("token_rate_limit", "threshold_percent")
    op.drop_column("token_rate_limit", "action")
    op.drop_column("token_rate_limit", "model_configuration_id")
    op.drop_column("token_rate_limit", "user_group_id")
    op.alter_column(
        "token_rate_limit",
        "scope",
        type_=sa.String(length=OLD_SCOPE_LENGTH),
        existing_type=sa.String(),
    )
