"""tenant usage counter

Adds tenant_usage_counter, one row per usage type per period, and copies the
usage in tenant_usage into it. tenant_usage stays for one release so that a
rollback still finds its data.

Revision ID: db8e1bfe4729
Revises: 00a73eb4dccf
Create Date: 2026-11-27 20:05:59.840834

"""

from alembic import op
import sqlalchemy as sa

from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS


# revision identifiers, used by Alembic.
revision = "db8e1bfe4729"
down_revision = "00a73eb4dccf"
branch_labels = None
depends_on = None


# Every tenant_usage row is one calendar period of USAGE_LIMIT_WINDOW_SECONDS.
# The copied row must end where the server's calendar period ends, or the
# server never reads it. Reading the setting is safe for the template schema:
# its tenant_usage is empty, so this copies no rows there. Zero amounts are
# skipped: a missing row already reads as 0.
_COPY_TENANT_USAGE = """
INSERT INTO tenant_usage_counter
    (usage_type, window_anchor, window_start, window_end, amount, updated_at)
SELECT
    counted.usage_type,
    'calendar',
    tenant_usage.window_start,
    tenant_usage.window_start + make_interval(secs => :window_seconds),
    counted.amount,
    coalesce(tenant_usage.updated_at, tenant_usage.window_start)
FROM tenant_usage
CROSS JOIN LATERAL (
    VALUES
        ('llm_cost_cents', tenant_usage.llm_cost_cents::numeric),
        ('chunks_indexed', tenant_usage.chunks_indexed::numeric),
        ('api_calls', tenant_usage.api_calls::numeric),
        ('non_streaming_api_calls', tenant_usage.non_streaming_api_calls::numeric)
) AS counted (usage_type, amount)
WHERE counted.amount <> 0
ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "tenant_usage_counter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usage_type", sa.String(length=40), nullable=False),
        sa.Column("window_anchor", sa.String(length=20), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_tenant_usage_counter_period",
        "tenant_usage_counter",
        [
            "usage_type",
            "window_anchor",
            "window_start",
            # Same as TENANT_USAGE_COUNTER_PERIOD_END_KEY in onyx.db.models.
            sa.text("COALESCE(window_end, 'infinity'::timestamp with time zone)"),
        ],
        unique=True,
    )
    op.execute(
        sa.text(_COPY_TENANT_USAGE).bindparams(
            window_seconds=USAGE_LIMIT_WINDOW_SECONDS
        )
    )


def downgrade() -> None:
    op.drop_index("uq_tenant_usage_counter_period", table_name="tenant_usage_counter")
    op.drop_table("tenant_usage_counter")
