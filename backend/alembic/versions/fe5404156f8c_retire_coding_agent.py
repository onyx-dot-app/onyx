"""Retire the coding agent and keep its saved answers readable.

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
        UPDATE tool_call c SET
            result = jsonb_build_object('tool_name', t.name, 'tool_call_id', c.tool_call_id,
                                        'content', c.tool_call_response),
            display_name = COALESCE(c.display_name, t.display_name)
        FROM tool t, chat_message m
        WHERE c.tool_id = t.id AND t.in_code_tool_id = 'CodingAgentTool'
          AND c.parent_chat_message_id = m.id AND m.response_status IS NULL
          AND (c.result IS NULL OR c.result = 'null'::jsonb) AND c.tool_call_response <> ''
    """)
    # Failed commands need a public result to replay stdout and stderr.
    op.execute("""
        UPDATE tool_call SET result = CASE
            WHEN result @> '{"is_error": true, "details": {"type": "bash_execution"}}'
            THEN jsonb_set(result, '{details}', jsonb_build_object(
                'type', 'custom_tool_result', 'tool_name', result->>'tool_name',
                'response_type', 'text', 'tool_result', result->>'content'))
            ELSE result - 'details'
        END
        WHERE result #>> '{details,type}' IN ('coding_result','bash_execution')
    """)
    op.execute("""
        UPDATE chat_response_item
        SET rendering = jsonb_set(rendering, '{mode}', CASE rendering->>'mode'
            WHEN 'coding_answer' THEN '"silent"'::jsonb ELSE '"answer"'::jsonb END)
        WHERE rendering->>'mode' IN ('coding_answer','coding_thinking')
    """)

    op.execute("""
        WITH retired AS (
            SELECT jsonb_build_object('type', 'capability', 'tool_id', id) AS entry
            FROM tool WHERE in_code_tool_id = 'CodingAgentTool'
        )
        UPDATE chat_session SET tool_options = tool_options - 'preferred'
        WHERE tool_options->'preferred' IN (SELECT entry FROM retired)
    """)
    op.execute("""
        WITH retired AS (
            SELECT jsonb_build_object('type', 'capability', 'tool_id', id) AS entry
            FROM tool WHERE in_code_tool_id = 'CodingAgentTool'
        )
        UPDATE chat_session SET tool_options = jsonb_set(tool_options, '{allowed}', (
            SELECT COALESCE(jsonb_agg(item ORDER BY ord), '[]'::jsonb)
            FROM jsonb_array_elements(tool_options->'allowed') WITH ORDINALITY a(item, ord)
            WHERE item NOT IN (SELECT entry FROM retired)
        ))
        WHERE EXISTS (SELECT 1 FROM retired WHERE tool_options->'allowed' @> jsonb_build_array(entry))
    """)
    op.execute("""
        UPDATE assistant__user_specific_config
        SET disabled_tool_ids = array_remove(disabled_tool_ids, tool.id)
        FROM tool WHERE tool.in_code_tool_id = 'CodingAgentTool'
          AND tool.id = ANY(disabled_tool_ids)
    """)
    op.execute("DELETE FROM tool WHERE in_code_tool_id = 'CodingAgentTool'")


def downgrade() -> None:
    # The deleted selections and original rendering cannot be reconstructed.
    op.execute("""
        INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
        VALUES ('coding_agent', 'Coding Agent',
                'Investigate and answer a coding question against a specific GitHub repository. '
                'Clones the repo into an isolated sandbox and explores it via shell commands before returning a text answer.',
                'CodingAgentTool', true)
    """)
