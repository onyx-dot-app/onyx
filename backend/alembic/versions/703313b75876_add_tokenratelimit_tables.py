"""Add TokenRateLimit Tables

Revision ID: 703313b75876
Revises: fad14119fb92
Create Date: 2024-04-15 01:36:02.952809

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "703313b75876"
down_revision = "fad14119fb92"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "token_rate_limit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("period_hours", sa.Integer(), nullable=False),
        sa.Column(
            "scope",
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "token_rate_limit__user_group",
        sa.Column("rate_limit_id", sa.Integer(), nullable=False),
        sa.Column("user_group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rate_limit_id"],
            ["token_rate_limit.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"],
            ["user_group.id"],
        ),
        sa.PrimaryKeyConstraint("rate_limit_id", "user_group_id"),
    )

    # NOTE: rate limit settings used to be stored in the "token_budget_settings" key in the
    # KeyValueStore. This will now be lost. The KV store works differently than it used to
    # so the migration is fairly complicated and likely not worth it to support (pretty much
    # nobody will have it set)


def downgrade() -> None:
    op.drop_table("token_rate_limit__user_group")
    op.drop_table("token_rate_limit")
