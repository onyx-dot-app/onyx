"""persona__skill association

Revision ID: dfe0f30fd0ce
Revises: f3a9c1d4b7e2
Create Date: 2026-06-15 14:10:31.504739

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "dfe0f30fd0ce"
down_revision = "f3a9c1d4b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona__skill",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skill.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("persona_id", "skill_id"),
    )
    # The composite PK (persona_id, skill_id) already serves persona_id-prefix
    # lookups, so only the reverse lookup (which personas reference a skill)
    # needs its own index.
    op.create_index("ix_persona__skill_skill_id", "persona__skill", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_persona__skill_skill_id", table_name="persona__skill")
    op.drop_table("persona__skill")
