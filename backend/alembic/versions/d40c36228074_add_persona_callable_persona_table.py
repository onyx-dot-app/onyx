"""add_persona_callable_persona_table

Revision ID: d40c36228074
Revises: 41fa44bef321
Create Date: 2026-01-26 22:34:25.941121

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d40c36228074"
down_revision = "41fa44bef321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona__callable_persona",
        sa.Column("caller_persona_id", sa.Integer(), nullable=False),
        sa.Column("callee_persona_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["caller_persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["callee_persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("caller_persona_id", "callee_persona_id"),
    )


def downgrade() -> None:
    op.drop_table("persona__callable_persona")
