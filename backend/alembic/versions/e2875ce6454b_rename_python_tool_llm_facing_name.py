"""rename python tool llm facing name

OpenAI reserves the function name "python" for its own harness and rejects
requests that define a tool with that name (400 invalid_request_error,
enforced server-side since 2026-07-21). The LLM-facing name of the Code
Interpreter tool moves to "run_python"; display_name and in_code_tool_id
are unchanged.

Revision ID: e2875ce6454b
Revises: eec4fc85ef28
Create Date: 2026-07-21 08:33:15.857244

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e2875ce6454b"
down_revision = "eec4fc85ef28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tool SET name = 'run_python' "
            "WHERE in_code_tool_id = 'PythonTool' AND name = 'python'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tool SET name = 'python' "
            "WHERE in_code_tool_id = 'PythonTool' AND name = 'run_python'"
        )
    )
