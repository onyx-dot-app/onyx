"""add_python_tool

Revision ID: c7e9f4a3b2d1
Revises: 9drpiiw74ljy
Create Date: 2025-11-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7e9f4a3b2d1"
down_revision = "9drpiiw74ljy"
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
            # in the UI, call it `Analysis` for easier understanding of what is should primarily be used for
            "display_name": "Analysis",
            "description": (
                "The Analysis Action allows the assistant to execute "
                "Python code in a secure, isolated environment for data analysis, "
                "computation, visualization, and file processing."
            ),
            "in_code_tool_id": "PythonTool",
            "enabled": True,
        },
    )


def downgrade() -> None:
    # We don't remove the tool on downgrade since it's totally fine to just
    # have it around. If we upgrade again, it will be a no-op.
    pass
