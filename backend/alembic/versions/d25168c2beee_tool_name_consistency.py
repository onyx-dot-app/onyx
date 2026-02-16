"""tool_name_consistency

Revision ID: d25168c2beee
Revises: 8405ca81cc83
Create Date: 2026-01-11 17:54:40.135777

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d25168c2beee"
down_revision = "8405ca81cc83"
branch_labels = None
depends_on = None


# Currently the seeded tools have the in_code_tool_id == name
CURRENT_TOOL_NAME_MAPPING = [
    "SearchTool",
    "WebSearchTool",
    "ImageGenerationTool",
    "PythonTool",
    "OpenURLTool",
    "KnowledgeGraphTool",
    "ResearchAgent",
]

# Mapping of in_code_tool_id -> name
# These are the expected names that we want in the database
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


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse the migration by setting name back to in_code_tool_id
    # This matches the original pattern where name was the class name
    for in_code_tool_id in CURRENT_TOOL_NAME_MAPPING:
        conn.execute(
            sa.text(
                """
                UPDATE tool
                SET name = :current_name
                WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            {
                "current_name": in_code_tool_id,
                "in_code_tool_id": in_code_tool_id,
            },
        )
