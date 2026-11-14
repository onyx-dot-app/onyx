"""seed postgres query tool

Revision ID: 732fa0cf2ad1
Revises: 414dfccc5e24
Create Date: 2026-07-24 15:05:05.636999

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "732fa0cf2ad1"
down_revision = "414dfccc5e24"
branch_labels = None
depends_on = None


POSTGRES_TOOL = {
    "name": "postgres_query",
    "display_name": "Knowledge Base Query",
    "description": (
        "Structured, permission-scoped queries over Onyx metadata: exact "
        "document counts and listings by source/title/date/owner/folder, "
        "source folder browsing, the user's own chat history, and the "
        "documents past answers cited."
    ),
    "in_code_tool_id": "PostgresTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text(
            "SELECT in_code_tool_id FROM tool WHERE in_code_tool_id = :in_code_tool_id"
        ),
        {"in_code_tool_id": POSTGRES_TOOL["in_code_tool_id"]},
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
            POSTGRES_TOOL,
        )
    else:
        conn.execute(
            sa.text(
                """
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """
            ),
            POSTGRES_TOOL,
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Detach from any personas first — persona__tool has no ON DELETE CASCADE.
    conn.execute(
        sa.text(
            """
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id
            )
            """
        ),
        {"in_code_tool_id": POSTGRES_TOOL["in_code_tool_id"]},
    )
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": POSTGRES_TOOL["in_code_tool_id"]},
    )
