"""Migrate to contextual rag model

Revision ID: 19c0ccb01687
Revises: b51c6844d1df
Create Date: 2026-02-12 11:21:41.798037

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "19c0ccb01687"
down_revision = "b51c6844d1df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # For every search_settings row that has contextual rag configured,
    # create an llm_model_flow entry with is_default=False.
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

    # Set is_default=TRUE for the flow that belongs to the current
    # (PRESENT) search settings. contextual rag must be enabled,
    # and the model name and provider must be defined
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
    pass
