"""add python tool on default

Revision ID: 57122d037335
Revises: c0c937d5c9e5
Create Date: 2026-02-27 10:10:40.124925

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "57122d037335"
down_revision = "c0c937d5c9e5"
branch_labels = None
depends_on = None


PYTHON_TOOL_NAME = "python"


def upgrade() -> None:
    conn = op.get_bind()

    # Look up the PythonTool id
    result = conn.execute(
        sa.text("SELECT id FROM tool WHERE name = :name"),
        {"name": PYTHON_TOOL_NAME},
    ).fetchone()

    if not result:
        return

    tool_id = result[0]

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

    result = conn.execute(
        sa.text("SELECT id FROM tool WHERE name = :name"),
        {"name": PYTHON_TOOL_NAME},
    ).fetchone()

    if not result:
        return

    conn.execute(
        sa.text(
            """
            DELETE FROM persona__tool
            WHERE persona_id = 0 AND tool_id = :tool_id
            """
        ),
        {"tool_id": result[0]},
    )
