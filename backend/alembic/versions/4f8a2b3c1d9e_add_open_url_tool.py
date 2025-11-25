"""add_open_url_tool

Revision ID: 4f8a2b3c1d9e
Revises: a852cbe15577
Create Date: 2025-11-24 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4f8a2b3c1d9e"
down_revision = "a852cbe15577"
branch_labels = None
depends_on = None


OPEN_URL_TOOL = {
    "name": "OpenURLTool",
    "display_name": "Open URL",
    "description": (
        "The Open URL Action allows the agent to fetch and read contents of web pages."
    ),
    "in_code_tool_id": "OpenURLTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    # Check if tool already exists
    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": OPEN_URL_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
        tool_id = existing[0]
        # Update existing tool
        conn.execute(
            sa.text(
                """
                UPDATE tool
                SET name = :name,
                    display_name = :display_name,
                    description = :description
                WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            OPEN_URL_TOOL,
        )
    else:
        # Insert new tool
        conn.execute(
            sa.text(
                """
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """
            ),
            OPEN_URL_TOOL,
        )
        # Get the newly inserted tool's id
        result = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
            {"in_code_tool_id": OPEN_URL_TOOL["in_code_tool_id"]},
        ).fetchone()
        tool_id = result[0]

    # Associate the tool with all existing personas
    # Get all persona IDs
    persona_ids = conn.execute(sa.text("SELECT id FROM persona")).fetchall()

    for (persona_id,) in persona_ids:
        # Check if association already exists
        exists = conn.execute(
            sa.text(
                """
                SELECT 1 FROM persona__tool
                WHERE persona_id = :persona_id AND tool_id = :tool_id
                """
            ),
            {"persona_id": persona_id, "tool_id": tool_id},
        ).fetchone()

        if not exists:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO persona__tool (persona_id, tool_id)
                    VALUES (:persona_id, :tool_id)
                    """
                ),
                {"persona_id": persona_id, "tool_id": tool_id},
            )


def downgrade() -> None:
    # We don't remove the tool on downgrade since it's fine to have it around.
    # If we upgrade again, it will be a no-op.
    pass
