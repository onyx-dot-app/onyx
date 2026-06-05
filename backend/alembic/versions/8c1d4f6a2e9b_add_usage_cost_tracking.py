"""add usage + cost tracking schema

Creates the per-user usage rollup table and the per-model cost-override table,
and adds a cost budget to token rate limits (token budget becomes nullable so a
limit can be token-only, cost-only, or both).

Revision ID: 8c1d4f6a2e9b
Revises: f3a9c1d4b7e2
Create Date: 2026-06-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy

# revision identifiers, used by Alembic.
revision = "8c1d4f6a2e9b"
down_revision = "f3a9c1d4b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_cost_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_cost_per_mtok", sa.Float(), nullable=False),
        sa.Column("output_cost_per_mtok", sa.Float(), nullable=False),
        # null cache rate bills cache reads at the input rate (litellm default).
        sa.Column("cache_read_cost_per_mtok", sa.Float(), nullable=True),
        # The model's onupdate=func.now() is ORM-side only (not DDL), so
        # updated_at auto-bumps on ORM writes but not on raw-SQL UPDATEs.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model", name="uq_model_cost_override_model"),
    )

    op.create_table(
        "user_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column(
            "window_start", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("flow", sa.String(), nullable=False),
        # Empty string (not NULL) for "no provider" so the dedup unique index
        # works on every Postgres version (NULLS NOT DISTINCT is PG15+ only).
        sa.Column("provider", sa.String(), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "cache_read_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cost_cents", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_usage_user_id", "user_usage", ["user_id"], unique=False)
    # Upsert key. provider is non-null ('' when absent), so a plain unique index
    # dedups correctly on every Postgres version (no PG15-only NULLS NOT DISTINCT).
    op.create_index(
        "uq_user_usage_dims",
        "user_usage",
        ["user_id", "window_start", "model", "flow", "provider"],
        unique=True,
    )

    op.add_column(
        "token_rate_limit",
        sa.Column("cost_budget_cents", sa.Float(), nullable=True),
    )
    op.alter_column("token_rate_limit", "token_budget", nullable=True)
    # A limit must carry a token budget, a cost budget, or both — never neither.
    op.create_check_constraint(
        "ck_token_rate_limit_budget_set",
        "token_rate_limit",
        "token_budget IS NOT NULL OR cost_budget_cents IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_token_rate_limit_budget_set", "token_rate_limit", type_="check"
    )
    # token_budget goes back to NOT NULL; back-fill any cost-only rows first so
    # the alter can't fail on NULLs.
    op.execute(
        "UPDATE token_rate_limit SET token_budget = 0 WHERE token_budget IS NULL"
    )
    op.alter_column("token_rate_limit", "token_budget", nullable=False)
    op.drop_column("token_rate_limit", "cost_budget_cents")
    op.drop_index("uq_user_usage_dims", table_name="user_usage")
    op.drop_index("ix_user_usage_user_id", table_name="user_usage")
    op.drop_index("ix_user_usage_window_start", table_name="user_usage")
    op.drop_table("user_usage")
    op.drop_table("model_cost_override")
