"""contextual_rag_model_configuration_fk

Revision ID: 4ff2545411ad
Revises: f0db5f1c6370
Create Date: 2026-05-06 11:09:28.087586

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4ff2545411ad"
down_revision = "f0db5f1c6370"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add FK column
    op.add_column(
        "search_settings",
        sa.Column("contextual_rag_model_configuration_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_search_settings_contextual_rag_model_configuration",
        "search_settings",
        "model_configuration",
        ["contextual_rag_model_configuration_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Data migration: populate from existing string columns
    op.execute("""
        UPDATE search_settings ss
        SET contextual_rag_model_configuration_id = mc.id
        FROM llm_provider lp
        JOIN model_configuration mc ON mc.llm_provider_id = lp.id
            AND mc.name = ss.contextual_rag_llm_name
        WHERE lp.name = ss.contextual_rag_llm_provider
          AND ss.contextual_rag_llm_name IS NOT NULL
          AND ss.contextual_rag_llm_provider IS NOT NULL
    """)

    # 3. Drop the string columns
    op.drop_column("search_settings", "contextual_rag_llm_name")
    op.drop_column("search_settings", "contextual_rag_llm_provider")


def downgrade() -> None:
    # Re-add string columns
    op.add_column(
        "search_settings",
        sa.Column("contextual_rag_llm_name", sa.String(), nullable=True),
    )
    op.add_column(
        "search_settings",
        sa.Column("contextual_rag_llm_provider", sa.String(), nullable=True),
    )

    # Back-fill from FK
    op.execute("""
        UPDATE search_settings ss
        SET contextual_rag_llm_name    = mc.name,
            contextual_rag_llm_provider = lp.name
        FROM model_configuration mc
        JOIN llm_provider lp ON lp.id = mc.llm_provider_id
        WHERE mc.id = ss.contextual_rag_model_configuration_id
          AND ss.contextual_rag_model_configuration_id IS NOT NULL
    """)

    op.drop_constraint(
        "fk_search_settings_contextual_rag_model_configuration",
        "search_settings",
        type_="foreignkey",
    )
    op.drop_column("search_settings", "contextual_rag_model_configuration_id")
