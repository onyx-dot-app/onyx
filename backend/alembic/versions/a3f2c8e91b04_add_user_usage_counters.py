"""add per-user usage counters

Revision ID: a3f2c8e91b04
Revises: d8cdfee5df80
Create Date: 2026-04-01 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a3f2c8e91b04"
down_revision = "8188861f4e92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_usage_counter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("counter_key", sa.String(64), nullable=False),
        sa.Column("current_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_value", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("user_id", "counter_key", name="uq_user_usage_counter"),
        sa.Index("ix_user_usage_counter_user_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_usage_counter")
