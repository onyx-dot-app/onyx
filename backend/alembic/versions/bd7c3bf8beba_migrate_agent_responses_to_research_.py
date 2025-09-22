"""migrate_agent_sub_questions_to_research_iterations

Revision ID: bd7c3bf8beba
Revises: f8a9b2c3d4e5
Create Date: 2025-08-18 11:33:27.098287

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "bd7c3bf8beba"
down_revision = "f8a9b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get connection to execute raw SQL
    connection = op.get_bind()

    # First, insert data into research_agent_iteration table
    # This creates one iteration record per primary_question_id using the earliest time_created
    connection.execute(
        sa.text(
            """
            INSERT INTO research_agent_iteration (primary_question_id, created_at, iteration_nr, purpose, reasoning)
            SELECT
                primary_question_id,
                MIN(time_created) as created_at,
                1 as iteration_nr,
                'Generating and researching subquestions' as purpose,
                '(No previous reasoning)' as reasoning
            FROM agent__sub_question
            JOIN chat_message on agent__sub_question.primary_question_id = chat_message.id
            WHERE primary_question_id IS NOT NULL
                AND chat_message.is_agentic = true
            GROUP BY primary_question_id
            ON CONFLICT DO NOTHING;
        """
        )
    )

    # Then, insert data into research_agent_iteration_sub_step table
    # This migrates each sub-question as a sub-step
    connection.execute(
        sa.text(
            """
            INSERT INTO research_agent_iteration_sub_step (
                primary_question_id,
                iteration_nr,
                iteration_sub_step_nr,
                created_at,
                sub_step_instructions,
                sub_step_tool_id,
                sub_answer,
                cited_doc_results
            )
            SELECT
                primary_question_id,
                1 as iteration_nr,
                level_question_num as iteration_sub_step_nr,
                time_created as created_at,
                sub_question as sub_step_instructions,
                1 as sub_step_tool_id,
                sub_answer,
                sub_question_doc_results as cited_doc_results
            FROM agent__sub_question
            JOIN chat_message on agent__sub_question.primary_question_id = chat_message.id
            WHERE chat_message.is_agentic = true
            AND primary_question_id IS NOT NULL
            ON CONFLICT DO NOTHING;
        """
        )
    )

    # Update chat_message records: set legacy agentic type and answer purpose for existing agentic messages
    connection.execute(
        sa.text(
            """
            UPDATE chat_message
            SET research_answer_purpose = 'ANSWER'
            WHERE is_agentic = true
            AND research_type IS NULL and
                message_type = 'ASSISTANT';
        """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE chat_message
            SET research_type = 'LEGACY_AGENTIC'
            WHERE is_agentic = true
            AND research_type IS NULL;
        """
        )
    )


def downgrade() -> None:
    # Get connection to execute raw SQL
    connection = op.get_bind()

    # Note: This downgrade removes all research agent iteration data
    # There's no way to perfectly restore the original agent__sub_question data
    # if it was deleted after this migration

    # Delete all research_agent_iteration_sub_step records that were migrated
    connection.execute(
        sa.text(
            """
            DELETE FROM research_agent_iteration_sub_step
            USING chat_message
            WHERE research_agent_iteration_sub_step.primary_question_id = chat_message.id
            AND chat_message.research_type = 'LEGACY_AGENTIC';
        """
        )
    )

    # Delete all research_agent_iteration records that were migrated
    connection.execute(
        sa.text(
            """
            DELETE FROM research_agent_iteration
            USING chat_message
            WHERE research_agent_iteration.primary_question_id = chat_message.id
            AND chat_message.research_type = 'LEGACY_AGENTIC';
        """
        )
    )

    # Revert chat_message updates: clear research fields for legacy agentic messages
    connection.execute(
        sa.text(
            """
            UPDATE chat_message
            SET research_type = NULL,
                research_answer_purpose = NULL
            WHERE is_agentic = true
            AND research_type = 'LEGACY_AGENTIC'
            AND message_type = 'ASSISTANT';
        """
        )
    )
