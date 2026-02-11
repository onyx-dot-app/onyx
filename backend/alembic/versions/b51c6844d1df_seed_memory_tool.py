"""seed_memory_tool

Revision ID: b51c6844d1df
Revises: 175ea04c7087
Create Date: 2026-02-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b51c6844d1df"
down_revision = "175ea04c7087"
branch_labels = None
depends_on = None


MEMORY_TOOL = {
    "name": "MemoryTool",
    "display_name": "Add Memory",
    "description": "Save memories about the user for future conversations.",
    "in_code_tool_id": "MemoryTool",
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text(
            "SELECT in_code_tool_id FROM tool WHERE in_code_tool_id = :in_code_tool_id"
        ),
        {"in_code_tool_id": MEMORY_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
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
            MEMORY_TOOL,
        )
    else:
        conn.execute(
            sa.text(
                """
                INSERT INTO tool (name, display_name, description, in_code_tool_id)
                VALUES (:name, :display_name, :description, :in_code_tool_id)
                """
            ),
            MEMORY_TOOL,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": MEMORY_TOOL["in_code_tool_id"]},
    )
