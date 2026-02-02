"""Add flow mapping table

Revision ID: f220515df7b4
Revises: cbc03e08d0f3
Create Date: 2026-01-30 12:21:24.955922

"""

from onyx.db.enums import LLMModelFlowType
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f220515df7b4"
down_revision = "9d1543a37106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_model_flow",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "llm_model_flow_type",
            sa.Enum(LLMModelFlowType, name="llmmodelflowtype", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("model_configuration_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["model_configuration_id"], ["model_configuration.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "llm_model_flow_type",
            "model_configuration_id",
            name="uq_model_config_per_llm_model_flow_type",
        ),
    )

    # Partial unique index so that there is at most one default for each flow type
    op.create_index(
        "ix_one_default_per_llm_model_flow",
        "llm_model_flow",
        ["llm_model_flow_type"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )


def downgrade() -> None:
    # Drop the llm_model_flow table (index is dropped automatically with table)
    op.drop_table("llm_model_flow")
