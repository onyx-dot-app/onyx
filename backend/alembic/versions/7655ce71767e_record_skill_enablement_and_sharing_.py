"""Record Skill enablement and sharing times

Revision ID: 7655ce71767e
Revises: ef73786dc783
Create Date: 2026-11-08 09:27:26.191868

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7655ce71767e"
down_revision = "ef73786dc783"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_skill_preference",
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    for table in ("skill__user", "skill__user_group"):
        # Add the default separately so existing shares keep an unknown date.
        op.add_column(
            table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.alter_column(table, "created_at", server_default=sa.func.clock_timestamp())


def downgrade() -> None:
    for table in ("skill__user_group", "skill__user"):
        op.drop_column(table, "created_at")
    op.drop_column("user_skill_preference", "enabled_at")
