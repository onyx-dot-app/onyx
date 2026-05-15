"""dalle3 deprecation

Revision ID: 37b5864e9cff
Revises: 2c7f9d3a84a0
Create Date: 2026-05-12 10:29:16.985208

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "37b5864e9cff"
down_revision = "2c7f9d3a84a0"
branch_labels = None
depends_on = None


_DEPRECATED_IMAGE_PROVIDER_IDS = ("openai_dalle_3", "azure_dalle_3")

_NEW_IMAGE_GENERATION_TOOL_DESCRIPTION = (
    "The Image Generation Action allows the agent to use GPT-IMAGE-1 to generate images. "
    "The action will be used when the user asks the agent to generate an image."
)


def upgrade() -> None:
    conn = op.get_bind()

    # Collect llm_provider IDs that back the deprecated image generation configs
    # so we can clean them up after deleting the configs. Each image gen config
    # owns its own LLM provider (created exclusively for image gen), and the
    # LLMProvider -> ModelConfiguration FK cascade-deletes the model configuration.
    llm_provider_ids = [
        row[0]
        for row in conn.execute(
            sa.text("""
                SELECT mc.llm_provider_id
                FROM image_generation_config igc
                JOIN model_configuration mc
                    ON mc.id = igc.model_configuration_id
                WHERE igc.image_provider_id = ANY(:provider_ids)
                """),
            {"provider_ids": list(_DEPRECATED_IMAGE_PROVIDER_IDS)},
        ).fetchall()
    ]

    conn.execute(
        sa.text(
            "DELETE FROM image_generation_config "
            "WHERE image_provider_id = ANY(:provider_ids)"
        ),
        {"provider_ids": list(_DEPRECATED_IMAGE_PROVIDER_IDS)},
    )

    if llm_provider_ids:
        conn.execute(
            sa.text(
                "DELETE FROM llm_provider__user_group "
                "WHERE llm_provider_id = ANY(:llm_provider_ids)"
            ),
            {"llm_provider_ids": llm_provider_ids},
        )
        conn.execute(
            sa.text("DELETE FROM llm_provider WHERE id = ANY(:llm_provider_ids)"),
            {"llm_provider_ids": llm_provider_ids},
        )

    conn.execute(
        sa.text(
            "UPDATE tool SET description = :description "
            "WHERE in_code_tool_id = 'ImageGenerationTool'"
        ),
        {"description": _NEW_IMAGE_GENERATION_TOOL_DESCRIPTION},
    )


def downgrade() -> None:
    pass
