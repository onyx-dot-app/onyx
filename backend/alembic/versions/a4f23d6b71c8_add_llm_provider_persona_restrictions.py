"""add llm provider persona restrictions

Revision ID: a4f23d6b71c8
Revises: 6f4f86aef280
Create Date: 2025-10-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a4f23d6b71c8"
down_revision = "6f4f86aef280"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider__persona",
        sa.Column("llm_provider_id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["llm_provider_id"], ["llm_provider.id"]),
        sa.ForeignKeyConstraint(["persona_id"], ["persona.id"]),
        sa.PrimaryKeyConstraint("llm_provider_id", "persona_id"),
    )
    op.create_index(
        "ix_llm_provider__persona_llm_provider_id",
        "llm_provider__persona",
        ["llm_provider_id"],
    )
    op.create_index(
        "ix_llm_provider__persona_persona_id",
        "llm_provider__persona",
        ["persona_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_provider__persona_persona_id",
        table_name="llm_provider__persona",
    )
    op.drop_index(
        "ix_llm_provider__persona_llm_provider_id",
        table_name="llm_provider__persona",
    )
    op.drop_table("llm_provider__persona")
