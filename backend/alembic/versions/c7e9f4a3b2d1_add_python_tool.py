"""add_python_tool

Revision ID: c7e9f4a3b2d1
Revises: a4f23d6b71c8
Create Date: 2025-11-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7e9f4a3b2d1"
down_revision = "a4f23d6b71c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add PythonTool to built-in tools"""
    conn = op.get_bind()

    # Start transaction
    conn.execute(sa.text("BEGIN"))

    try:
        # Check if PythonTool already exists
        existing_tool = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = 'PythonTool'")
        ).fetchone()

        if not existing_tool:
            # Insert PythonTool
            conn.execute(
                sa.text(
                    """
                    INSERT INTO tool (name, display_name, description, in_code_tool_id)
                    VALUES (:name, :display_name, :description, :in_code_tool_id)
                    """
                ),
                {
                    "name": "PythonTool",
                    "display_name": "Python Execution",
                    "description": (
                        "The Python Execution Action allows the assistant to execute "
                        "Python code in a secure, isolated environment for data analysis, "
                        "computation, visualization, and file processing."
                    ),
                    "in_code_tool_id": "PythonTool",
                },
            )

        # Commit transaction
        conn.execute(sa.text("COMMIT"))

    except Exception as e:
        # Rollback on error
        conn.execute(sa.text("ROLLBACK"))
        raise e


def downgrade() -> None:
    # We don't remove the tool on downgrade since it's totally fine to just
    # have it around. If we upgrade again, it will be a no-op.
    pass
