"""retain user usage after user deletion

Revision ID: 0d9c7b6a5e4f
Revises: f57f35403f6c
Create Date: 2026-07-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0d9c7b6a5e4f"
down_revision = "f57f35403f6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CASCADE erased a deleted user's spend history, so historical org totals
    # shrank on every offboard. API-key principals are user rows too, so
    # deleting a key erased its spend as well.
    op.drop_constraint("user_usage_user_id_fkey", "user_usage", type_="foreignkey")
    op.alter_column("user_usage", "user_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        "user_usage_user_id_fkey",
        "user_usage",
        "user",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("user_usage_user_id_fkey", "user_usage", type_="foreignkey")
    # Orphaned rows cannot satisfy the NOT NULL constraint being restored.
    op.execute("DELETE FROM user_usage WHERE user_id IS NULL")
    op.alter_column("user_usage", "user_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key(
        "user_usage_user_id_fkey",
        "user_usage",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
