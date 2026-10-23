"""move retired gpt-image-1 image gen config to the default model

Revision ID: cf5fe008f2f1
Revises: c5178de73522
Create Date: 2026-10-23 18:45:11.430622

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.image_generation import DEFAULT_IMAGE_MODEL_NAME
from onyx.db.image_generation import DEFAULT_IMAGE_PROVIDER_ID


# revision identifiers, used by Alembic.
revision = "cf5fe008f2f1"
down_revision = "c5178de73522"
branch_labels = None
depends_on = None

RETIRED_IMAGE_PROVIDER_ID = "openai_gpt_image_1"


def upgrade() -> None:
    conn = op.get_bind()

    retired = conn.execute(
        sa.text(
            "SELECT igc.is_default, mc.id AS model_configuration_id, mc.llm_provider_id "
            "FROM image_generation_config igc "
            "JOIN model_configuration mc ON mc.id = igc.model_configuration_id "
            "WHERE igc.image_provider_id = :retired_id"
        ),
        {"retired_id": RETIRED_IMAGE_PROVIDER_ID},
    ).fetchone()
    if retired is None:
        return

    replacement_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM image_generation_config WHERE image_provider_id = :default_id"
        ),
        {"default_id": DEFAULT_IMAGE_PROVIDER_ID},
    ).scalar()

    if replacement_exists:
        if retired.is_default:
            conn.execute(
                sa.text(
                    "UPDATE image_generation_config SET is_default = true "
                    "WHERE image_provider_id = :default_id"
                ),
                {"default_id": DEFAULT_IMAGE_PROVIDER_ID},
            )
        conn.execute(
            sa.text(
                "DELETE FROM image_generation_config WHERE image_provider_id = :retired_id"
            ),
            {"retired_id": RETIRED_IMAGE_PROVIDER_ID},
        )
        conn.execute(
            sa.text(
                "DELETE FROM llm_provider__user_group WHERE llm_provider_id = :provider_id"
            ),
            {"provider_id": retired.llm_provider_id},
        )
        conn.execute(
            sa.text("DELETE FROM llm_provider WHERE id = :provider_id"),
            {"provider_id": retired.llm_provider_id},
        )
        return

    conn.execute(
        sa.text("UPDATE model_configuration SET name = :model_name WHERE id = :id"),
        {"model_name": DEFAULT_IMAGE_MODEL_NAME, "id": retired.model_configuration_id},
    )
    conn.execute(
        sa.text(
            "UPDATE llm_provider SET name = :name, default_model_name = :model_name "
            "WHERE id = :provider_id"
        ),
        {
            "name": f"Image Gen - {DEFAULT_IMAGE_PROVIDER_ID}",
            "model_name": DEFAULT_IMAGE_MODEL_NAME,
            "provider_id": retired.llm_provider_id,
        },
    )
    conn.execute(
        sa.text(
            "UPDATE image_generation_config SET image_provider_id = :default_id "
            "WHERE image_provider_id = :retired_id"
        ),
        {
            "default_id": DEFAULT_IMAGE_PROVIDER_ID,
            "retired_id": RETIRED_IMAGE_PROVIDER_ID,
        },
    )


def downgrade() -> None:
    pass
