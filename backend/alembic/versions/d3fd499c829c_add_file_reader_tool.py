"""add_file_reader_tool

Revision ID: d3fd499c829c
Revises: 114a638452db
Create Date: 2026-02-07 19:28:22.452337

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d3fd499c829c"
down_revision = "114a638452db"
branch_labels = None
depends_on = None

FILE_READER_TOOL = {
    "name": "read_file",
    "display_name": "File Reader",
    "description": (
        "Read sections of user-uploaded files by character offset. "
        "Useful for inspecting large files that cannot fit entirely in context."
    ),
    "in_code_tool_id": "FileReaderTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    # Check if tool already exists
    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": FILE_READER_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
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
            FILE_READER_TOOL,
        )
        tool_id = existing[0]
    else:
        # Insert new tool
        result = conn.execute(
            sa.text(
                """
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                RETURNING id
                """
            ),
            FILE_READER_TOOL,
        )
        tool_id = result.scalar_one()

    # Attach to the default persona (id=0) if not already attached
    conn.execute(
        sa.text(
            """
            INSERT INTO persona__tool (persona_id, tool_id)
            VALUES (0, :tool_id)
            ON CONFLICT DO NOTHING
            """
        ),
        {"tool_id": tool_id},
    )


def downgrade() -> None:
    conn = op.get_bind()
    in_code_tool_id = FILE_READER_TOOL["in_code_tool_id"]

    # Remove persona associations first (FK constraint)
    conn.execute(
        sa.text(
            """
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id
            )
            """
        ),
        {"in_code_tool_id": in_code_tool_id},
    )

    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": in_code_tool_id},
    )
