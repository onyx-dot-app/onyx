"""Remove the coding agent from the catalog and disabled tool lists.

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
