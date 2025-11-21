"""add_python_tool

Revision ID: c7e9f4a3b2d1
Revises: 3c9a65f1207f
Create Date: 2025-11-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7e9f4a3b2d1"
down_revision = "3c9a65f1207f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add PythonTool to built-in tools"""
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
            VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
            """
        ),
        {
            "name": "PythonTool",
            # in the UI, call it `Code Interpreter` since this is a well known term for this tool
            "display_name": "Code Interpreter",
            "description": (
                "The Code Interpreter Action allows the assistant to execute "
                "Python code in a secure, isolated environment for data analysis, "
                "computation, visualization, and file processing."
            ),
            "in_code_tool_id": "PythonTool",
            "enabled": True,
        },
    )


def downgrade() -> None:
    """Remove PythonTool from built-in tools"""
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            DELETE FROM tool
            WHERE in_code_tool_id = :in_code_tool_id
            """
        ),
        {
            "in_code_tool_id": "PythonTool",
        },
    )
