"""add model_role table

Revision ID: 609429379ca0
Revises: ce6d912380d7
Create Date: 2026-11-25 15:31:09.986790

Moves the deployment's model choices ("which model answers chats") out of the
`is_default` flags on `llm_model_flow` and `image_generation_config` into
`model_role`, one row per role. `llm_model_flow` keeps only capabilities, so
the job rows (CHAT_NAMING, SEARCH_SELECTION, CRAFT, CONTEXTUAL_RAG), which
existed only to carry a default, are deleted. The contextual RAG model stays
on `search_settings`, which was already its source.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "609429379ca0"
down_revision = "ce6d912380d7"
branch_labels = None
depends_on = None

MODEL_ROLES = (
    "CHAT",
    "IMAGE_PROCESSING",
    "CHAT_NAMING",
    "SEARCH_SELECTION",
    "DECISION",
    "CRAFT",
    "IMAGE_GENERATION",
)

# Role -> the flow whose default held it before this revision.
ROLE_FROM_FLOW = {
    "CHAT": "CHAT",
    "IMAGE_PROCESSING": "VISION",
    "CHAT_NAMING": "CHAT_NAMING",
    "SEARCH_SELECTION": "SEARCH_SELECTION",
    "DECISION": "DECISION",
    "CRAFT": "CRAFT",
}

JOB_FLOWS = ("CHAT_NAMING", "SEARCH_SELECTION", "CRAFT", "CONTEXTUAL_RAG")


def upgrade() -> None:
    op.create_table(
        "model_role",
        sa.Column(
            "role",
            sa.Enum(*MODEL_ROLES, name="modelrole", native_enum=False),
            primary_key=True,
        ),
        sa.Column(
            "model_configuration_id",
            sa.Integer(),
            sa.ForeignKey("model_configuration.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    for role, flow in ROLE_FROM_FLOW.items():
        op.execute(
            sa.text(
                "INSERT INTO model_role (role, model_configuration_id) "
                "SELECT :role, model_configuration_id FROM llm_model_flow "
                "WHERE llm_model_flow_type = :flow AND is_default IS TRUE "
                "LIMIT 1"
            ).bindparams(role=role, flow=flow)
        )
    op.execute(
        "INSERT INTO model_role (role, model_configuration_id) "
        "SELECT 'IMAGE_GENERATION', model_configuration_id "
        "FROM image_generation_config WHERE is_default IS TRUE "
        "ORDER BY image_provider_id LIMIT 1"
    )

    op.execute(
        sa.text(
            "DELETE FROM llm_model_flow WHERE llm_model_flow_type IN :flows"
        ).bindparams(sa.bindparam("flows", value=JOB_FLOWS, expanding=True))
    )

    op.drop_index("ix_one_default_per_llm_model_flow", table_name="llm_model_flow")
    op.drop_column("llm_model_flow", "is_default")
    op.drop_index(
        "ix_image_generation_config_is_default", table_name="image_generation_config"
    )
    op.drop_column("image_generation_config", "is_default")


def downgrade() -> None:
    op.add_column(
        "llm_model_flow",
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "image_generation_config",
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )

    # The job flows existed only to carry a default; restore the held ones.
    for role in ("CHAT_NAMING", "SEARCH_SELECTION", "CRAFT"):
        op.execute(
            sa.text(
                "INSERT INTO llm_model_flow "
                "(llm_model_flow_type, model_configuration_id, is_default) "
                "SELECT :role, model_configuration_id, false FROM model_role "
                "WHERE role = :role AND model_configuration_id IS NOT NULL "
                "ON CONFLICT DO NOTHING"
            ).bindparams(role=role)
        )
    op.execute(
        "INSERT INTO llm_model_flow "
        "(llm_model_flow_type, model_configuration_id, is_default) "
        "SELECT 'CONTEXTUAL_RAG', contextual_rag_model_configuration_id, true "
        "FROM search_settings WHERE status = 'PRESENT' "
        "AND enable_contextual_rag IS TRUE "
        "AND contextual_rag_model_configuration_id IS NOT NULL "
        "ORDER BY id DESC LIMIT 1 "
        "ON CONFLICT DO NOTHING"
    )

    for role, flow in ROLE_FROM_FLOW.items():
        op.execute(
            sa.text(
                "UPDATE llm_model_flow SET is_default = true FROM model_role "
                "WHERE model_role.role = :role "
                "AND llm_model_flow.model_configuration_id "
                "= model_role.model_configuration_id "
                "AND llm_model_flow.llm_model_flow_type = :flow"
            ).bindparams(role=role, flow=flow)
        )
    op.execute(
        "UPDATE image_generation_config SET is_default = true "
        "WHERE image_provider_id = ("
        "SELECT c.image_provider_id FROM image_generation_config c "
        "JOIN model_role r ON r.model_configuration_id = c.model_configuration_id "
        "WHERE r.role = 'IMAGE_GENERATION' "
        "ORDER BY c.image_provider_id LIMIT 1)"
    )

    op.create_index(
        "ix_one_default_per_llm_model_flow",
        "llm_model_flow",
        ["llm_model_flow_type"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )
    op.create_index(
        "ix_image_generation_config_is_default",
        "image_generation_config",
        ["is_default"],
        unique=False,
    )
    op.drop_table("model_role")
