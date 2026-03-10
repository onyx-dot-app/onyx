"""seed_memory_tool and add enable_memory_tool to user

Revision ID: b51c6844d1df
Revises: 93c15d6a6fbb
Create Date: 2026-02-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b51c6844d1df"
down_revision = "93c15d6a6fbb"
branch_labels = None
depends_on = None


MEMORY_TOOL = {
    "name": "MemoryTool",
    "display_name": "Add Memory",
    "description": "Save memories about the user for future conversations.",
    "in_code_tool_id": "MemoryTool",
    "enabled": True,
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
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """
            ),
            MEMORY_TOOL,
        )

    op.add_column(
        "user",
        sa.Column(
            "enable_memory_tool",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "enable_memory_tool")

    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": MEMORY_TOOL["in_code_tool_id"]},
    )
