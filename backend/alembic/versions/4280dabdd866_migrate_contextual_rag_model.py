"""Migrate contextual rag model

Revision ID: 4280dabdd866
Revises: 114a638452db
Create Date: 2026-02-11 15:44:30.033412

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "4280dabdd866"
down_revision = "114a638452db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: For every search_settings row that has contextual RAG configured,
    # create an llm_model_flow entry with is_default=FALSE.
    # contextual_rag_llm_provider stores the llm_provider.name (a string),
    # so we join through llm_provider to reach model_configuration.
    op.execute(
        """
        INSERT INTO llm_model_flow (llm_model_flow_type, model_configuration_id, is_default)
        SELECT DISTINCT
            'CONTEXTUAL_RAG',
            mc.id,
            FALSE
        FROM search_settings ss
        JOIN llm_provider lp
            ON lp.name = ss.contextual_rag_llm_provider
        JOIN model_configuration mc
            ON mc.llm_provider_id = lp.id
            AND mc.name = ss.contextual_rag_llm_name
        WHERE ss.enable_contextual_rag = TRUE
            AND ss.contextual_rag_llm_name IS NOT NULL
            AND ss.contextual_rag_llm_provider IS NOT NULL
        ON CONFLICT (llm_model_flow_type, model_configuration_id) DO NOTHING
        """
    )

    # Step 2: Set is_default=TRUE for the flow that belongs to the current
    # (PRESENT) search setting.
    op.execute(
        """
        UPDATE llm_model_flow
        SET is_default = TRUE
        WHERE llm_model_flow_type = 'CONTEXTUAL_RAG'
            AND model_configuration_id = (
                SELECT mc.id
                FROM search_settings ss
                JOIN llm_provider lp
                    ON lp.name = ss.contextual_rag_llm_provider
                JOIN model_configuration mc
                    ON mc.llm_provider_id = lp.id
                    AND mc.name = ss.contextual_rag_llm_name
                WHERE ss.status = 'PRESENT'
                    AND ss.enable_contextual_rag = TRUE
                    AND ss.contextual_rag_llm_name IS NOT NULL
                    AND ss.contextual_rag_llm_provider IS NOT NULL
                ORDER BY ss.id DESC
                LIMIT 1
            )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM llm_model_flow
        WHERE llm_model_flow_type = 'CONTEXTUAL_RAG'
        """
    )
