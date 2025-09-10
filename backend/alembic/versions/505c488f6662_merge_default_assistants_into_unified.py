"""merge_default_assistants_into_unified

Revision ID: 505c488f6662
Revises: d09fc20a3c66
Create Date: 2025-09-09 19:00:56.816626

"""

import json
from typing import Any
from typing import NamedTuple
from uuid import UUID

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "505c488f6662"
down_revision = "d09fc20a3c66"
branch_labels = None
depends_on = None

# Constants for the unified assistant
UNIFIED_ASSISTANT_NAME = "Assistant"
UNIFIED_ASSISTANT_DESCRIPTION = (
    "Your AI assistant with search, web browsing, and image generation capabilities."
)
UNIFIED_ASSISTANT_NUM_CHUNKS = 25
UNIFIED_ASSISTANT_DISPLAY_PRIORITY = 0
UNIFIED_ASSISTANT_LLM_FILTER_EXTRACTION = True
UNIFIED_ASSISTANT_LLM_RELEVANCE_FILTER = False
UNIFIED_ASSISTANT_RECENCY_BIAS = "AUTO"  # NOTE: needs to be capitalized
UNIFIED_ASSISTANT_CHUNKS_ABOVE = 0
UNIFIED_ASSISTANT_CHUNKS_BELOW = 0
UNIFIED_ASSISTANT_DATETIME_AWARE = True

# NOTE: tool specific prompts are handled on the fly and automatically injected
# into the prompt before passing to the LLM.
DEFAULT_SYSTEM_PROMPT = """
You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the \
user's intent, ask clarifying questions when needed, think step-by-step through complex problems, \
provide clear and accurate answers, and proactively anticipate helpful follow-up information. Always \
prioritize being truthful, nuanced, insightful, and efficient.
The current date is [[CURRENT_DATETIME]]

You use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make \
your responses more readable and engaging.
You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, \
symbols, etc.: '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline.
For code you prefer to use Markdown and specify the language.
You can use Markdown horizontal rules (---) to separate sections of your responses.
You can use Markdown tables to format your responses for data, lists, and other structured information.
""".strip()


INSERT_DICT: dict[str, Any] = {
    "name": UNIFIED_ASSISTANT_NAME,
    "description": UNIFIED_ASSISTANT_DESCRIPTION,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "num_chunks": UNIFIED_ASSISTANT_NUM_CHUNKS,
    "display_priority": UNIFIED_ASSISTANT_DISPLAY_PRIORITY,
    "llm_filter_extraction": UNIFIED_ASSISTANT_LLM_FILTER_EXTRACTION,
    "llm_relevance_filter": UNIFIED_ASSISTANT_LLM_RELEVANCE_FILTER,
    "recency_bias": UNIFIED_ASSISTANT_RECENCY_BIAS,
    "chunks_above": UNIFIED_ASSISTANT_CHUNKS_ABOVE,
    "chunks_below": UNIFIED_ASSISTANT_CHUNKS_BELOW,
    "datetime_aware": UNIFIED_ASSISTANT_DATETIME_AWARE,
}

GENERAL_ASSISTANT_ID = -1
ART_ASSISTANT_ID = -3


class UserRow(NamedTuple):
    """Typed representation of user row from database query."""

    id: UUID
    chosen_assistants: list[int] | None
    visible_assistants: list[int] | None
    hidden_assistants: list[int] | None
    pinned_assistants: list[int] | None


def upgrade() -> None:
    conn = op.get_bind()

    # Start transaction
    conn.execute(sa.text("BEGIN"))

    try:
        # Step 1: Create or update the unified assistant (ID 0)
        search_assistant = conn.execute(
            sa.text("SELECT * FROM persona WHERE id = 0")
        ).fetchone()

        if search_assistant:
            # Update existing Search assistant to be the unified assistant
            conn.execute(
                sa.text(
                    """
                    UPDATE persona
                    SET name = :name,
                        description = :description,
                        system_prompt = :system_prompt,
                        num_chunks = :num_chunks,
                        is_default_persona = true,
                        is_visible = true,
                        deleted = false,
                        display_priority = :display_priority,
                        llm_filter_extraction = :llm_filter_extraction,
                        llm_relevance_filter = :llm_relevance_filter,
                        recency_bias = :recency_bias,
                        chunks_above = :chunks_above,
                        chunks_below = :chunks_below,
                        datetime_aware = :datetime_aware,
                        starter_messages = null
                    WHERE id = 0
                """
                ),
                INSERT_DICT,
            )
        else:
            # Create new unified assistant with ID 0
            conn.execute(
                sa.text(
                    """
                    INSERT INTO persona (
                        id, name, description, system_prompt, num_chunks,
                        is_default_persona, is_visible, deleted, display_priority,
                        llm_filter_extraction, llm_relevance_filter, recency_bias,
                        chunks_above, chunks_below, datetime_aware, starter_messages,
                        builtin_persona
                    ) VALUES (
                        0, :name, :description, :system_prompt, :num_chunks,
                        true, true, false, :display_priority, :llm_filter_extraction,
                        :llm_relevance_filter, :recency_bias, :chunks_above, :chunks_below,
                        :datetime_aware, null, true
                    )
                """
                ),
                INSERT_DICT,
            )

        # Step 2: Mark ALL builtin assistants as deleted (except the unified assistant ID 0)
        conn.execute(
            sa.text(
                """
                UPDATE persona
                SET deleted = true, is_visible = false, is_default_persona = false
                WHERE builtin_persona = true AND id != 0
            """
            )
        )

        # Step 3: Add all built-in tools to the unified assistant
        # First, get the tool IDs for SearchTool, ImageGenerationTool, and WebSearchTool
        search_tool = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = 'SearchTool'")
        ).fetchone()

        if not search_tool:
            raise ValueError(
                "SearchTool not found in database. Ensure tools migration has run first."
            )

        image_gen_tool = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = 'ImageGenerationTool'")
        ).fetchone()

        if not image_gen_tool:
            raise ValueError(
                "ImageGenerationTool not found in database. Ensure tools migration has run first."
            )

        # WebSearchTool is optional - may not be configured
        web_search_tool = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = 'WebSearchTool'")
        ).fetchone()

        # Clear existing tool associations for persona 0
        conn.execute(sa.text("DELETE FROM persona__tool WHERE persona_id = 0"))

        # Add tools to the unified assistant
        conn.execute(
            sa.text(
                """
                INSERT INTO persona__tool (persona_id, tool_id)
                VALUES (0, :tool_id)
                ON CONFLICT DO NOTHING
            """
            ),
            {"tool_id": search_tool[0]},
        )

        conn.execute(
            sa.text(
                """
                INSERT INTO persona__tool (persona_id, tool_id)
                VALUES (0, :tool_id)
                ON CONFLICT DO NOTHING
            """
            ),
            {"tool_id": image_gen_tool[0]},
        )

        if web_search_tool:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO persona__tool (persona_id, tool_id)
                    VALUES (0, :tool_id)
                    ON CONFLICT DO NOTHING
                """
                ),
                {"tool_id": web_search_tool[0]},
            )

        # Step 4: Migrate existing chat sessions from all builtin assistants to unified assistant
        conn.execute(
            sa.text(
                """
                UPDATE chat_session
                SET persona_id = 0
                WHERE persona_id IN (
                    SELECT id FROM persona WHERE builtin_persona = true AND id != 0
                )
            """
            )
        )

        # Step 5: Migrate user preferences - remove references to all builtin assistants
        # First, get all builtin assistant IDs (except 0)
        builtin_assistants_result = conn.execute(
            sa.text(
                """
                SELECT id FROM persona
                WHERE builtin_persona = true AND id != 0
            """
            )
        ).fetchall()
        builtin_assistant_ids = [row[0] for row in builtin_assistants_result]

        # Get all users with preferences
        users_result = conn.execute(
            sa.text(
                """
                SELECT id, chosen_assistants, visible_assistants,
                       hidden_assistants, pinned_assistants
                FROM "user"
            """
            )
        ).fetchall()

        for user_row in users_result:
            user = UserRow(*user_row)
            user_id: UUID = user.id
            updates: dict[str, Any] = {}

            # Remove all builtin assistants from chosen_assistants
            if user.chosen_assistants:
                new_chosen: list[int] = [
                    assistant_id
                    for assistant_id in user.chosen_assistants
                    if assistant_id not in builtin_assistant_ids
                ]
                if new_chosen != user.chosen_assistants:
                    updates["chosen_assistants"] = json.dumps(new_chosen)

            # Remove all builtin assistants from visible_assistants
            if user.visible_assistants:
                new_visible: list[int] = [
                    assistant_id
                    for assistant_id in user.visible_assistants
                    if assistant_id not in builtin_assistant_ids
                ]
                if new_visible != user.visible_assistants:
                    updates["visible_assistants"] = json.dumps(new_visible)

            # Add all builtin assistants to hidden_assistants
            if user.hidden_assistants:
                new_hidden: list[int] = list(user.hidden_assistants)
                for old_id in builtin_assistant_ids:
                    if old_id not in new_hidden:
                        new_hidden.append(old_id)
                if new_hidden != user.hidden_assistants:
                    updates["hidden_assistants"] = json.dumps(new_hidden)
            else:
                updates["hidden_assistants"] = json.dumps(builtin_assistant_ids)

            # Remove all builtin assistants from pinned_assistants
            if user.pinned_assistants:
                new_pinned: list[int] = [
                    assistant_id
                    for assistant_id in user.pinned_assistants
                    if assistant_id not in builtin_assistant_ids
                ]
                if new_pinned != user.pinned_assistants:
                    updates["pinned_assistants"] = json.dumps(new_pinned)

            # Apply updates if any
            if updates:
                set_clause = ", ".join([f"{k} = :{k}" for k in updates.keys()])
                updates["user_id"] = str(user_id)  # Convert UUID to string for SQL
                conn.execute(
                    sa.text(f'UPDATE "user" SET {set_clause} WHERE id = :user_id'),
                    updates,
                )

        # Commit transaction
        conn.execute(sa.text("COMMIT"))

    except Exception as e:
        # Rollback on error
        conn.execute(sa.text("ROLLBACK"))
        raise e


def downgrade() -> None:
    conn = op.get_bind()

    # Start transaction
    conn.execute(sa.text("BEGIN"))

    try:
        # Only restore General (ID -1) and Art (ID -3) assistants
        # Step 1: Keep Search assistant (ID 0) as default but restore original state
        conn.execute(
            sa.text(
                """
                UPDATE persona
                SET is_default_persona = true,
                    is_visible = true,
                    deleted = false
                WHERE id = 0
            """
            )
        )

        # Step 2: Restore General assistant (ID -1)
        conn.execute(
            sa.text(
                """
                UPDATE persona
                SET deleted = false,
                    is_visible = true,
                    is_default_persona = true
                WHERE id = :general_assistant_id
            """
            ),
            {"general_assistant_id": GENERAL_ASSISTANT_ID},
        )

        # Step 3: Restore Art assistant (ID -3)
        conn.execute(
            sa.text(
                """
                UPDATE persona
                SET deleted = false,
                    is_visible = true,
                    is_default_persona = true
                WHERE id = :art_assistant_id
            """
            ),
            {"art_assistant_id": ART_ASSISTANT_ID},
        )

        # Note: We don't restore the original tool associations, names, or descriptions
        # as those would require more complex logic to determine original state.
        # We also cannot restore original chat session persona_ids as we don't
        # have the original mappings.
        # Other builtin assistants remain deleted as per the requirement.

        # Commit transaction
        conn.execute(sa.text("COMMIT"))

    except Exception as e:
        # Rollback on error
        conn.execute(sa.text("ROLLBACK"))
        raise e
