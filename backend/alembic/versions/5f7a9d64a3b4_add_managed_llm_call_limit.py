"""Add managed LLM call limit and provider ownership flag

Revision ID: 5f7a9d64a3b4
Revises: 9a0296d7421e
Create Date: 2025-02-26 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5f7a9d64a3b4"
down_revision = "9a0296d7421e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_provider",
        sa.Column(
            "is_onyx_managed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "managed_llm_call_limit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_call_limit", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.execute(
        "INSERT INTO managed_llm_call_limit (enabled, daily_call_limit) VALUES (true, 500)"
    )


def downgrade() -> None:
    op.drop_table("managed_llm_call_limit")
    op.drop_column("llm_provider", "is_onyx_managed")
