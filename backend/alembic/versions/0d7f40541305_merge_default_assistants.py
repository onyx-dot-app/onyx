"""merge_default_assistants

Revision ID: 0d7f40541305
Revises: abbfec3a5ac5
Create Date: 2025-09-06 18:25:49.827387

"""

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "0d7f40541305"
down_revision = "abbfec3a5ac5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Update the unified assistant (ID 0) with combined capabilities
    op.execute(
        text(
            """
            UPDATE persona
            SET name = 'Assistant',
                description = 'Your AI assistant with search, web browsing, and image generation capabilities.',
                system_prompt = :system_prompt,
                task_prompt = :task_prompt,
                num_chunks = 25,
                is_visible = true,
                is_default_persona = true
            WHERE id = 0
            """
        ).bindparams(
            system_prompt=(
                "You are a helpful AI assistant with multiple capabilities.\n"
                "The current date is [[CURRENT_DATETIME]].\n\n"
                "You can:\n"
                "1. Search and analyze documents from connected sources\n"
                "2. Browse the web for current information\n"
                "3. Generate images based on descriptions\n"
                "4. Assist with writing, analysis, coding, and various other tasks\n\n"
                "When searching documents:\n"
                "- Process and comprehend vast amounts of text to provide grounded, accurate answers\n"
                "- Clearly communicate ANY UNCERTAINTY in your answers\n\n"
                "When generating images:\n"
                "- Create high-quality images that accurately reflect user requirements\n"
                "- Maintain appropriate content standards\n\n"
                "You give concise responses to simple questions, but provide thorough responses to\n"
                "complex and open-ended questions. You use markdown where reasonable and for coding."
            ),
            task_prompt=(
                "When documents are provided:\n"
                "- Answer queries based on the documents\n"
                "- Ignore documents not directly relevant to the query\n"
                "- Don't refer to documents by number\n\n"
                "When generating images:\n"
                "- Create images that match the user's requirements\n"
                "- Pay attention to specified details, styles, and elements\n\n"
                "If no relevant documents exist and no image generation is needed, use chat history and internal knowledge."
            ),
        )
    )

    # 2. Mark General (ID 1) and Art (ID 3) as no longer default and not visible
    op.execute(
        text(
            """
            UPDATE persona
            SET is_default_persona = false,
                is_visible = false,
                deleted = true
            WHERE id IN (1, 3)
            """
        )
    )

    # 3. Mark Paraphrase (ID 2) as no longer default (but keep it visible if it was)
    op.execute(
        text(
            """
            UPDATE persona
            SET is_default_persona = false
            WHERE id = 2
            """
        )
    )

    # 4. Add all built-in tools to the unified assistant (ID 0)
    # First, add SearchTool if not already present
    op.execute(
        text(
            """
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT 0, id FROM tool
            WHERE in_code_tool_id = 'SearchTool'
            AND NOT EXISTS (
                SELECT 1 FROM persona__tool
                WHERE persona_id = 0
                AND tool_id = (SELECT id FROM tool WHERE in_code_tool_id = 'SearchTool')
            )
            """
        )
    )

    # Add ImageGenerationTool if available
    op.execute(
        text(
            """
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT 0, id FROM tool
            WHERE in_code_tool_id = 'ImageGenerationTool'
            AND NOT EXISTS (
                SELECT 1 FROM persona__tool
                WHERE persona_id = 0
                AND tool_id = (SELECT id FROM tool WHERE in_code_tool_id = 'ImageGenerationTool')
            )
            """
        )
    )

    # Add InternetSearchTool if available
    op.execute(
        text(
            """
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT 0, id FROM tool
            WHERE in_code_tool_id = 'InternetSearchTool'
            AND NOT EXISTS (
                SELECT 1 FROM persona__tool
                WHERE persona_id = 0
                AND tool_id = (SELECT id FROM tool WHERE in_code_tool_id = 'InternetSearchTool')
            )
            """
        )
    )

    # 5. Migrate user preferences - update chosen_assistants
    op.execute(
        text(
            """
            UPDATE "user"
            SET chosen_assistants =
                CASE
                    WHEN chosen_assistants IS NULL THEN NULL
                    WHEN chosen_assistants::jsonb @> '[1]'::jsonb OR chosen_assistants::jsonb @> '[3]'::jsonb THEN
                        CASE
                            WHEN chosen_assistants::jsonb @> '[0]'::jsonb THEN
                                -- Already has 0, just remove 1 and 3
                                (SELECT jsonb_agg(elem::int)
                                 FROM jsonb_array_elements(chosen_assistants::jsonb) elem
                                 WHERE elem::int NOT IN (1, 3))
                            ELSE
                                -- Replace 1 or 3 with 0, remove both
                                (SELECT jsonb_agg(DISTINCT elem)
                                 FROM (
                                     SELECT 0 AS elem
                                     UNION ALL
                                     SELECT elem::int
                                     FROM jsonb_array_elements(chosen_assistants::jsonb) elem
                                     WHERE elem::int NOT IN (1, 3)
                                 ) t)
                        END
                    ELSE chosen_assistants
                END
            WHERE chosen_assistants IS NOT NULL
            """
        )
    )

    # Update visible_assistants
    op.execute(
        text(
            """
            UPDATE "user"
            SET visible_assistants =
                CASE
                    WHEN visible_assistants::jsonb @> '[1]'::jsonb OR visible_assistants::jsonb @> '[3]'::jsonb THEN
                        CASE
                            WHEN visible_assistants::jsonb @> '[0]'::jsonb THEN
                                -- Already has 0, just remove 1 and 3
                                (SELECT COALESCE(jsonb_agg(elem::int), '[]'::jsonb)
                                 FROM jsonb_array_elements(visible_assistants::jsonb) elem
                                 WHERE elem::int NOT IN (1, 3))
                            ELSE
                                -- Replace 1 or 3 with 0, remove both
                                (SELECT COALESCE(jsonb_agg(DISTINCT elem), '[]'::jsonb)
                                 FROM (
                                     SELECT 0 AS elem
                                     UNION ALL
                                     SELECT elem::int
                                     FROM jsonb_array_elements(visible_assistants::jsonb) elem
                                     WHERE elem::int NOT IN (1, 3)
                                 ) t)
                        END
                    ELSE visible_assistants
                END
            """
        )
    )

    # Update hidden_assistants - add 1 and 3 if not already hidden
    op.execute(
        text(
            """
            UPDATE "user"
            SET hidden_assistants =
                (SELECT COALESCE(jsonb_agg(DISTINCT elem), '[]'::jsonb)
                 FROM (
                     SELECT elem::int AS elem
                     FROM jsonb_array_elements(hidden_assistants::jsonb) elem
                     UNION
                     SELECT 1
                     UNION
                     SELECT 3
                 ) t)
            """
        )
    )

    # Update pinned_assistants
    op.execute(
        text(
            """
            UPDATE "user"
            SET pinned_assistants =
                CASE
                    WHEN pinned_assistants IS NULL THEN NULL
                    WHEN pinned_assistants::jsonb @> '[1]'::jsonb OR pinned_assistants::jsonb @> '[3]'::jsonb THEN
                        CASE
                            WHEN pinned_assistants::jsonb @> '[0]'::jsonb THEN
                                -- Already has 0, just remove 1 and 3
                                (SELECT jsonb_agg(elem::int)
                                 FROM jsonb_array_elements(pinned_assistants::jsonb) elem
                                 WHERE elem::int NOT IN (1, 3))
                            ELSE
                                -- Replace 1 or 3 with 0, remove both
                                (SELECT jsonb_agg(DISTINCT elem)
                                 FROM (
                                     SELECT 0 AS elem
                                     UNION ALL
                                     SELECT elem::int
                                     FROM jsonb_array_elements(pinned_assistants::jsonb) elem
                                     WHERE elem::int NOT IN (1, 3)
                                 ) t)
                        END
                    ELSE pinned_assistants
                END
            WHERE pinned_assistants IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # 1. Restore the original Search assistant (ID 0)
    op.execute(
        text(
            """
            UPDATE persona
            SET name = 'Search',
                description = 'Assistant with access to documents and knowledge from Connected Sources.',
                system_prompt = :system_prompt,
                task_prompt = :task_prompt
            WHERE id = 0
            """
        ).bindparams(
            system_prompt=(
                "You are a question answering system that is constantly learning and improving.\n"
                "The current date is [[CURRENT_DATETIME]].\n\n"
                "You can process and comprehend vast amounts of text and utilize this knowledge to provide\n"
                "grounded, accurate, and concise answers to diverse queries.\n\n"
                "You always clearly communicate ANY UNCERTAINTY in your answer."
            ),
            task_prompt=(
                "Answer my query based on the documents provided.\n"
                "The documents may not all be relevant, ignore any documents that are not directly relevant\n"
                "to the most recent user query.\n\n"
                "I have not read or seen any of the documents and do not want to read them. "
                "Do not refer to them by Document number.\n\n"
                "If there are no relevant documents, refer to the chat history and your internal knowledge."
            ),
        )
    )

    # 2. Restore General (ID 1) and Art (ID 3) as default and visible
    op.execute(
        text(
            """
            UPDATE persona
            SET is_default_persona = true,
                is_visible = true,
                deleted = false
            WHERE id IN (1, 3)
            """
        )
    )

    # 3. Restore Paraphrase (ID 2) as default
    op.execute(
        text(
            """
            UPDATE persona
            SET is_default_persona = true
            WHERE id = 2
            """
        )
    )

    # 4. Remove ImageGenerationTool and InternetSearchTool from persona 0
    op.execute(
        text(
            """
            DELETE FROM persona__tool
            WHERE persona_id = 0
            AND tool_id IN (
                SELECT id FROM tool
                WHERE in_code_tool_id IN ('ImageGenerationTool', 'InternetSearchTool')
            )
            """
        )
    )

    # Note: We don't reverse the user preference migrations as they are complex
    # and users may have made additional changes since the migration
