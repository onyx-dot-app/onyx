"""add_python_tool

Revision ID: 1c3f8a7b5d4e
Revises: 505c488f6662
Create Date: 2025-02-14 00:00:00

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c3f8a7b5d4e"
down_revision = "505c488f6662"
branch_labels = None
depends_on = None


PYTHON_TOOL = {
    "name": "PythonTool",
    "display_name": "Code Interpreter",
    "description": (
        "The Code Interpreter Action lets assistants execute Python in an isolated runtime. "
        "It can process staged files, read and write artifacts, stream stdout and stderr, "
        "and return generated outputs for the chat session."
    ),
    "in_code_tool_id": "PythonTool",
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("BEGIN"))
    try:
        existing = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
            PYTHON_TOOL,
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
                PYTHON_TOOL,
            )
        else:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO tool (name, display_name, description, in_code_tool_id)
                    VALUES (:name, :display_name, :description, :in_code_tool_id)
                    """
                ),
                PYTHON_TOOL,
            )

        conn.execute(sa.text("COMMIT"))
    except Exception:
        conn.execute(sa.text("ROLLBACK"))
        raise


def downgrade() -> None:
    # Do not delete the tool entry on downgrade; leaving it is safe and keeps migrations idempotent.
    pass
