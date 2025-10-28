"""add target_persona_id to tool for agent tools

Revision ID: 22f7ce63361f
Revises: 23f0b9b49965
Create Date: 2025-10-27 17:59:00.068872

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "22f7ce63361f"
down_revision = "23f0b9b49965"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column("target_persona_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tool_target_persona_id_persona",
        "tool",
        "persona",
        ["target_persona_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tool_target_persona_id_persona", "tool", type_="foreignkey")
    op.drop_column("tool", "target_persona_id")
