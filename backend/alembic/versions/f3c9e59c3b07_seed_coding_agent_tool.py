"""seed_coding_agent_tool

Revision ID: f3c9e59c3b07
Revises: 1c36b3dc2f4e
Create Date: 2026-05-05 14:18:31.451207

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f3c9e59c3b07"
down_revision = "1c36b3dc2f4e"
branch_labels = None
depends_on = None


CODING_AGENT_TOOL = {
    "name": "coding_agent",
    "display_name": "Coding Agent",
    "description": (
        "Investigate and answer a coding question against a specific GitHub "
        "repository. Clones the repo into an isolated sandbox and explores "
        "it via shell commands before returning a text answer."
    ),
    "in_code_tool_id": "CodingAgentTool",
    "enabled": False,
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text(
            "SELECT in_code_tool_id FROM tool WHERE in_code_tool_id = :in_code_tool_id"
        ),
        {"in_code_tool_id": CODING_AGENT_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
        conn.execute(
            sa.text("""
                UPDATE tool
                SET name = :name,
                    display_name = :display_name,
                    description = :description
                WHERE in_code_tool_id = :in_code_tool_id
                """),
            CODING_AGENT_TOOL,
        )
    else:
        conn.execute(
            sa.text("""
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """),
            CODING_AGENT_TOOL,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": CODING_AGENT_TOOL["in_code_tool_id"]},
    )
