"""tool_name_consistency

Revision ID: 19a896a66d3f
Revises: a3c1a7904cd0
Create Date: 2026-01-11 10:40:18.400270

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "19a896a66d3f"
down_revision = "a3c1a7904cd0"
branch_labels = None
depends_on = None

# Mapping of in_code_tool_id to the NAME constant from each tool class
# These are the currently seeded tool names
CURRENT_TOOL_NAME_MAPPING = {
    "SearchTool": "SearchTool",
    "WebSearchTool": "WebSearchTool",
    "ImageGenerationTool": "ImageGenerationTool",
    "PythonTool": "PythonTool",
    "OpenURLTool": "OpenURLTool",
    "KnowledgeGraphTool": "KnowledgeGraphTool",
    "ResearchAgent": "ResearchAgent",
}

# Mapping of in_code_tool_id to the NAME constant from each tool class
# These are the expected tool names
EXPECTED_TOOL_NAME_MAPPING = {
    "SearchTool": "internal_search",
    "WebSearchTool": "web_search",
    "ImageGenerationTool": "generate_image",
    "PythonTool": "python",
    "OpenURLTool": "open_url",
    "KnowledgeGraphTool": "run_kg_search",
    "ResearchAgent": "research_agent",
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("BEGIN"))

    try:
        # Mapping of in_code_tool_id to the NAME constant from each tool class
        # These match the .name property of each tool implementation
        tool_name_mapping = EXPECTED_TOOL_NAME_MAPPING

        # Update the name column for each tool based on its in_code_tool_id
        for in_code_tool_id, expected_name in tool_name_mapping.items():
            conn.execute(
                sa.text(
                    """
                    UPDATE tool
                    SET name = :expected_name
                    WHERE in_code_tool_id = :in_code_tool_id
                    """
                ),
                {
                    "expected_name": expected_name,
                    "in_code_tool_id": in_code_tool_id,
                },
            )

        conn.execute(sa.text("COMMIT"))
    except Exception as e:
        conn.execute(sa.text("ROLLBACK"))
        raise e


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("BEGIN"))

    try:
        # Reverse the migration by setting name back to in_code_tool_id
        # This matches the original pattern where name was the class name
        for in_code_tool_id, current_name in CURRENT_TOOL_NAME_MAPPING.items():
            conn.execute(
                sa.text(
                    """
                    UPDATE tool
                    SET name = :current_name
                    WHERE in_code_tool_id = :in_code_tool_id
                    """
                ),
                {
                    "current_name": current_name,
                    "in_code_tool_id": in_code_tool_id,
                },
            )

        conn.execute(sa.text("COMMIT"))
    except Exception as e:
        conn.execute(sa.text("ROLLBACK"))
        raise e
