"""add image processing settings

Revision ID: 3f1a9c2e7b4d
Revises: ad99acb9be41
Create Date: 2026-09-21 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "3f1a9c2e7b4d"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None

_SETTINGS_KEY = "onyx_settings"
_ENABLED_KEY = "image_extraction_and_analysis_enabled"
_MAX_SIZE_KEY = "image_analysis_max_size_mb"
_DEFAULT_MAX_SIZE_MB = 20


def upgrade() -> None:
    op.create_table(
        "image_processing_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_configuration_id",
            sa.Integer(),
            sa.ForeignKey("model_configuration.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("max_size_mb", sa.Integer(), nullable=False),
    )
    op.create_index(
        "idx_image_processing_settings_singleton",
        "image_processing_settings",
        [sa.text("(true)")],
        unique=True,
    )

    bind = op.get_bind()

    # The old toggle lived in the workspace settings blob. The pydantic default
    # was True, and the reader treated an explicit None as off.
    settings_row = bind.execute(
        text(
            "SELECT value, encrypted_value IS NOT NULL FROM key_value_store "
            "WHERE key = :key"
        ),
        {"key": _SETTINGS_KEY},
    ).one_or_none()
    if settings_row is not None and settings_row[0] is None and settings_row[1]:
        # The app never writes these settings encrypted, so this is an
        # unexpected layout. Stop rather than silently reset the toggle.
        raise RuntimeError(
            f"key_value_store row '{_SETTINGS_KEY}' holds an encrypted payload; "
            "decrypt it into `value` before running this migration."
        )
    settings = dict(settings_row[0]) if settings_row and settings_row[0] else {}
    if _ENABLED_KEY in settings:
        enabled = (
            bool(settings[_ENABLED_KEY])
            if settings[_ENABLED_KEY] is not None
            else False
        )
    else:
        enabled = True
    max_size_mb = settings.get(_MAX_SIZE_KEY) or _DEFAULT_MAX_SIZE_MB

    # Only an explicit VISION default carries over. Installs that were
    # captioning through the old any-vision-model scan never chose a model,
    # so they land on off.
    vision_default_id = bind.execute(
        text(
            "SELECT model_configuration_id FROM llm_model_flow "
            "WHERE llm_model_flow_type = 'VISION' AND is_default IS TRUE"
        )
    ).scalar_one_or_none()

    if enabled and vision_default_id is not None:
        bind.execute(
            text(
                "INSERT INTO image_processing_settings "
                "(model_configuration_id, max_size_mb) VALUES (:mc, :max_size)"
            ),
            {"mc": vision_default_id, "max_size": int(max_size_mb)},
        )

    if settings_row is not None:
        bind.execute(
            text(
                "UPDATE key_value_store SET value = value - :enabled_key - :max_size_key "
                "WHERE key = :key"
            ),
            {
                "enabled_key": _ENABLED_KEY,
                "max_size_key": _MAX_SIZE_KEY,
                "key": _SETTINGS_KEY,
            },
        )

    # VISION and CONTEXTUAL_RAG rows stay as capability tags / membership, but
    # the is_default pointer on them has no reader after this migration. The
    # CONTEXTUAL_RAG pointer is rebuilt on downgrade from the search settings,
    # and the VISION pointer from the new row — so a VISION pointer that did
    # not carry over (the toggle was off) is kept as the only record of it.
    flow_types = "('VISION', 'CONTEXTUAL_RAG')"
    if not (enabled and vision_default_id is not None):
        flow_types = "('CONTEXTUAL_RAG')"
    bind.execute(
        text(
            "UPDATE llm_model_flow SET is_default = false "
            f"WHERE llm_model_flow_type IN {flow_types} AND is_default IS TRUE"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    row = bind.execute(
        text(
            "SELECT model_configuration_id, max_size_mb FROM image_processing_settings"
        )
    ).one_or_none()

    enabled = row is not None
    max_size_mb = row[1] if row else _DEFAULT_MAX_SIZE_MB
    # The settings row may not exist yet (a fresh install that never saved
    # workspace settings); the old reader then falls back to enabled=True, so
    # the patch is inserted rather than skipped.
    bind.execute(
        text(
            "INSERT INTO key_value_store (key, value) "
            "VALUES (:key, CAST(:patch AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = "
            "COALESCE(key_value_store.value, CAST('{}' AS jsonb)) || EXCLUDED.value"
        ),
        {
            "patch": f'{{"{_ENABLED_KEY}": {"true" if enabled else "false"}, '
            f'"{_MAX_SIZE_KEY}": {int(max_size_mb)}}}',
            "key": _SETTINGS_KEY,
        },
    )

    if row is not None:
        bind.execute(
            text(
                "UPDATE llm_model_flow SET is_default = true "
                "WHERE llm_model_flow_type = 'VISION' AND model_configuration_id = :mc"
            ),
            {"mc": row[0]},
        )

    # Restore the CONTEXTUAL_RAG pointer from the present search settings.
    bind.execute(
        text(
            "UPDATE llm_model_flow SET is_default = true "
            "WHERE llm_model_flow_type = 'CONTEXTUAL_RAG' AND model_configuration_id = ("
            "SELECT contextual_rag_model_configuration_id FROM search_settings "
            "WHERE status = 'PRESENT' AND enable_contextual_rag IS TRUE "
            "AND contextual_rag_model_configuration_id IS NOT NULL LIMIT 1)"
        )
    )

    op.drop_index(
        "idx_image_processing_settings_singleton",
        table_name="image_processing_settings",
    )
    op.drop_table("image_processing_settings")
