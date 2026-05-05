"""optional_provider_name_persona_id_override

Revision ID: e3bcc6cbe3bf
Revises: 74379b447d4c
Create Date: 2026-05-05 10:33:13.148334

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e3bcc6cbe3bf"
down_revision = "74379b447d4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Make llm_provider.name nullable and drop the unique constraint so that
    #    the display name is no longer the unique identifier for a provider.
    op.alter_column("llm_provider", "name", nullable=True)
    op.drop_constraint("llm_provider_name_key", "llm_provider", type_="unique")

    # 2. Add a proper integer FK column to persona so that the provider override
    #    is referenced by stable PK rather than the mutable display name string.
    op.add_column(
        "persona",
        sa.Column("llm_provider_override_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_persona_llm_provider_override",
        "persona",
        "llm_provider",
        ["llm_provider_override_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Data migration: convert the existing string-based override to the
    #    matching integer FK. Rows with no match (provider already deleted)
    #    are left as NULL, which is safe — they would have fallen back to the
    #    default provider anyway.
    op.execute("""
        UPDATE persona
        SET llm_provider_override_id = llm_provider.id
        FROM llm_provider
        WHERE persona.llm_model_provider_override = llm_provider.name
          AND persona.llm_model_provider_override IS NOT NULL
        """)


def downgrade() -> None:
    op.drop_constraint(
        "fk_persona_llm_provider_override", "persona", type_="foreignkey"
    )
    op.drop_column("persona", "llm_provider_override_id")
    op.create_unique_constraint("llm_provider_name_key", "llm_provider", ["name"])
    op.alter_column("llm_provider", "name", nullable=False)
