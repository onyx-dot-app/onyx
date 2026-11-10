"""Add user Skill limit blocks

Revision ID: e3241e0833c0
Revises: f27ab6f691ec
Create Date: 2026-11-08 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e3241e0833c0"
down_revision = "f27ab6f691ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_skill_limit_block",
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            sa.UUID(),
            sa.ForeignKey("skill.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("failed_limit", sa.String(length=5), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_skill_limit_block_skill_id", "user_skill_limit_block", ["skill_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_skill_limit_block_skill_id", table_name="user_skill_limit_block"
    )
    op.drop_table("user_skill_limit_block")
