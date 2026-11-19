"""Remove the coding agent from the tool catalog and saved preferences.

Revision ID: fe5404156f8c
Revises: 65f8d8cd1bf3
"""

from alembic import op

revision = "fe5404156f8c"
down_revision = "65f8d8cd1bf3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH retired AS (
            SELECT jsonb_build_object('type', 'capability', 'tool_id', id) AS entry
            FROM tool WHERE in_code_tool_id = 'CodingAgentTool'
        )
        UPDATE chat_session SET tool_options =
            CASE WHEN tool_options->'preferred' IN (SELECT entry FROM retired)
                 THEN tool_options - 'preferred' ELSE tool_options END
            || CASE WHEN jsonb_typeof(tool_options->'allowed') = 'array'
                    THEN jsonb_build_object('allowed', (
                        SELECT COALESCE(jsonb_agg(item ORDER BY ord), '[]'::jsonb)
                        FROM jsonb_array_elements(tool_options->'allowed')
                             WITH ORDINALITY AS a(item, ord)
                        WHERE item NOT IN (SELECT entry FROM retired)
                    ))
                    ELSE '{}'::jsonb END
        WHERE EXISTS (SELECT 1 FROM retired) AND EXISTS (
            SELECT 1 FROM retired
            WHERE tool_options->'preferred' = entry
               OR tool_options->'allowed' @> jsonb_build_array(entry)
        )
    """)
    op.execute("""
        WITH retired AS (SELECT id FROM tool WHERE in_code_tool_id = 'CodingAgentTool')
        UPDATE assistant__user_specific_config SET disabled_tool_ids = ARRAY(
            SELECT id FROM unnest(disabled_tool_ids) WITH ORDINALITY AS disabled(id, ord)
            WHERE id NOT IN (SELECT id FROM retired) ORDER BY ord
        )
        WHERE EXISTS (SELECT 1 FROM retired)
          AND disabled_tool_ids && ARRAY(SELECT id FROM retired)
    """)
    op.execute("DELETE FROM tool WHERE in_code_tool_id = 'CodingAgentTool'")


def downgrade() -> None:
    # The original selections cannot be reconstructed.
    op.execute("""
        INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
        VALUES ('coding_agent', 'Coding Agent',
                'Investigate and answer a coding question against a specific GitHub repository. '
                'Clones the repo into an isolated sandbox and explores it via shell commands before returning a text answer.',
                'CodingAgentTool', true)
    """)
