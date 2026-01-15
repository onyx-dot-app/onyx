"""add_deep_research_tool

Revision ID: c1d2e3f4a5b6
Revises: b8c9d0e1f2a3
Create Date: 2025-12-18 16:00:00.000000

"""

from alembic import op
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_DB_NAME
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


DEEP_RESEARCH_TOOL = {
    "name": RESEARCH_AGENT_DB_NAME,
    "display_name": "Research Agent",
    "description": "The Research Agent is a sub-agent that conducts research on a specific topic.",
    "in_code_tool_id": "ResearchAgent",
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
            VALUES (:name, :display_name, :description, :in_code_tool_id, false)
            """
        ),
        DEEP_RESEARCH_TOOL,
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM tool
            WHERE in_code_tool_id = :in_code_tool_id
            """
        ),
        {"in_code_tool_id": DEEP_RESEARCH_TOOL["in_code_tool_id"]},
    )
