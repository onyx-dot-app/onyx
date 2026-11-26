"""seed browser tool

Revision ID: 75b8e7305ef6
Revises: d04326aae2f9
Create Date: 2026-11-26 21:49:40.806763

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "75b8e7305ef6"
down_revision = "d04326aae2f9"
branch_labels = None
depends_on = None


DEFAULT_PERSONA_ID = 0

BROWSER_TOOL = {
    "name": "BrowserTool",
    "display_name": "Browser",
    "description": "Browse websites and act on pages in the sandbox's browser.",
    "in_code_tool_id": "BrowserTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": BROWSER_TOOL["in_code_tool_id"]},
    ).fetchone()
    if existing is None:
        conn.execute(
            sa.text("""
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """),
            BROWSER_TOOL,
        )

    # The default agent kept the browser before it became a tool.
    conn.execute(
        sa.text("""
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT :persona_id, id FROM tool WHERE in_code_tool_id = :in_code_tool_id
            AND EXISTS (SELECT 1 FROM persona WHERE id = :persona_id)
            ON CONFLICT DO NOTHING
            """),
        {
            "persona_id": DEFAULT_PERSONA_ID,
            "in_code_tool_id": BROWSER_TOOL["in_code_tool_id"],
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id
            )
            """),
        {"in_code_tool_id": BROWSER_TOOL["in_code_tool_id"]},
    )
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": BROWSER_TOOL["in_code_tool_id"]},
    )
