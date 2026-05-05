"""optional_provider_name_persona_id_override

Revision ID: e3bcc6cbe3bf
Revises: 74379b447d4c
Create Date: 2026-05-05 10:33:13.148334

"""

from alembic import op

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

    # 2. Data migration: populate default_model_configuration_id from the existing
    #    string pair (llm_model_provider_override, llm_model_version_override).
    #    default_model_configuration_id was added by a prior migration but never
    #    written to — this backfills it for all pre-existing personas.
    #    Rows with no match (provider/model deleted or mismatched) stay NULL and
    #    fall back to the default provider at runtime.
    op.execute("""
        UPDATE persona
        SET default_model_configuration_id = mc.id
        FROM llm_provider lp
        JOIN model_configuration mc ON mc.llm_provider_id = lp.id
        WHERE persona.llm_model_provider_override = lp.name
          AND persona.llm_model_version_override = mc.name
          AND persona.llm_model_provider_override IS NOT NULL
          AND persona.llm_model_version_override IS NOT NULL
          AND persona.default_model_configuration_id IS NULL
        """)


def downgrade() -> None:
    # Backfill any null names with the provider type before re-adding the NOT NULL
    # and UNIQUE constraints. Providers created after the upgrade may have null names.
    op.execute("UPDATE llm_provider SET name = provider WHERE name IS NULL")
    op.create_unique_constraint("llm_provider_name_key", "llm_provider", ["name"])
    op.alter_column("llm_provider", "name", nullable=False)
