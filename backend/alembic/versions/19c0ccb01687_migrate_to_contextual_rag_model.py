"""Migrate to contextual rag model

Revision ID: 19c0ccb01687
Revises: 9c54986124c6
Create Date: 2026-02-12 11:21:41.798037

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "19c0ccb01687"
down_revision = "9c54986124c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen the column to fit 'CONTEXTUAL_RAG' (15 chars); was varchar(10)
    # when the table was created with only CHAT/VISION values.
    op.alter_column(
        "llm_model_flow",
        "llm_model_flow_type",
        type_=sa.String(length=20),
        existing_type=sa.String(length=10),
        existing_nullable=False,
    )

    # For every search_settings row that has contextual rag configured,
    # create an llm_model_flow entry. is_default is TRUE if the row
    # belongs to the PRESENT search settings, FALSE otherwise.
    op.execute(
        """
        INSERT INTO llm_model_flow (llm_model_flow_type, model_configuration_id, is_default)
        SELECT DISTINCT
            'CONTEXTUAL_RAG',
            mc.id,
            (ss.status = 'PRESENT')
        FROM search_settings ss
        JOIN llm_provider lp
            ON lp.name = ss.contextual_rag_llm_provider
        JOIN model_configuration mc
            ON mc.llm_provider_id = lp.id
            AND mc.name = ss.contextual_rag_llm_name
        WHERE ss.enable_contextual_rag = TRUE
            AND ss.contextual_rag_llm_name IS NOT NULL
            AND ss.contextual_rag_llm_provider IS NOT NULL
        ON CONFLICT (llm_model_flow_type, model_configuration_id)
            DO UPDATE SET is_default = EXCLUDED.is_default
            WHERE EXCLUDED.is_default = TRUE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM llm_model_flow
        WHERE llm_model_flow_type = 'CONTEXTUAL_RAG'
        """
    )

    op.alter_column(
        "llm_model_flow",
        "llm_model_flow_type",
        type_=sa.String(length=10),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
