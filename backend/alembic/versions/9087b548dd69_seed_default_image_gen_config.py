"""seed_default_image_gen_config

Revision ID: 9087b548dd69
Revises: 2b90f3af54b8
Create Date: 2026-01-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9087b548dd69"
down_revision = "2b90f3af54b8"
branch_labels = None
depends_on = None

# Constants for default image generation config
# Source: web/src/app/admin/configuration/image-generation/constants.ts
IMAGE_PROVIDER_ID = "openai_gpt_image_1"
MODEL_NAME = "gpt-image-1"
PROVIDER_NAME = "openai"


def upgrade() -> None:
    conn = op.get_bind()

    # Check if image_generation_config table already has records
    existing_configs = (
        conn.execute(sa.text("SELECT COUNT(*) FROM image_generation_config")).scalar()
        or 0
    )

    if existing_configs > 0:
        # Skip if configs already exist - user may have configured manually
        return

    # Find the first OpenAI LLM provider
    openai_provider = conn.execute(
        sa.text(
            """
            SELECT id, api_key
            FROM llm_provider
            WHERE provider = :provider
            ORDER BY id
            LIMIT 1
            """
        ),
        {"provider": PROVIDER_NAME},
    ).fetchone()

    if not openai_provider:
        # No OpenAI provider found - nothing to do
        return

    source_provider_id, api_key = openai_provider

    # Create new LLM provider for image generation (clone only api_key)
    result = conn.execute(
        sa.text(
            """
            INSERT INTO llm_provider (
                name, provider, api_key, api_base, api_version,
                deployment_name, default_model_name, is_public,
                is_default_provider, is_default_vision_provider, is_auto_mode
            )
            VALUES (
                :name, :provider, :api_key, NULL, NULL,
                NULL, :default_model_name, :is_public,
                NULL, NULL, :is_auto_mode
            )
            RETURNING id
            """
        ),
        {
            "name": f"Image Gen - {IMAGE_PROVIDER_ID}",
            "provider": PROVIDER_NAME,
            "api_key": api_key,
            "default_model_name": MODEL_NAME,
            "is_public": True,
            "is_auto_mode": False,
        },
    )
    new_provider_id = result.scalar()

    # Create model configuration
    result = conn.execute(
        sa.text(
            """
            INSERT INTO model_configuration (
                llm_provider_id, name, is_visible, max_input_tokens,
                supports_image_input, display_name
            )
            VALUES (
                :llm_provider_id, :name, :is_visible, :max_input_tokens,
                :supports_image_input, :display_name
            )
            RETURNING id
            """
        ),
        {
            "llm_provider_id": new_provider_id,
            "name": MODEL_NAME,
            "is_visible": True,
            "max_input_tokens": None,
            "supports_image_input": False,
            "display_name": None,
        },
    )
    model_config_id = result.scalar()

    # Create image generation config
    conn.execute(
        sa.text(
            """
            INSERT INTO image_generation_config (
                image_provider_id, model_configuration_id, is_default
            )
            VALUES (
                :image_provider_id, :model_configuration_id, :is_default
            )
            """
        ),
        {
            "image_provider_id": IMAGE_PROVIDER_ID,
            "model_configuration_id": model_config_id,
            "is_default": True,
        },
    )


def downgrade() -> None:
    # We don't remove the config on downgrade since it's safe to keep around
    # If we upgrade again, it will be a no-op due to the existing records check
    pass
