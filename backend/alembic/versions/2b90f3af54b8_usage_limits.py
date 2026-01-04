"""usage_limits

Revision ID: 2b90f3af54b8
Revises: 9a0296d7421e
Create Date: 2026-01-03 16:55:30.449692

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2b90f3af54b8"
down_revision = "9a0296d7421e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "window_start", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("llm_cost_cents", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("chunks_indexed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "non_streaming_api_calls", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("window_start", name="uq_tenant_usage_window"),
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_usage_window_start", table_name="tenant_usage")
    op.drop_table("tenant_usage")
