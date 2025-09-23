"""seed_builtin_tools

Revision ID: d09fc20a3c66
Revises: b7ec9b5b505f
Create Date: 2025-09-09 19:32:16.824373

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d09fc20a3c66"
down_revision = "b7ec9b5b505f"
branch_labels = None
depends_on = None


# Tool definitions - core tools that should always be seeded
# Names/in_code_tool_id are the same as the class names in the tool_implementations package
BUILT_IN_TOOLS = [
    {
        "name": "SearchTool",
        "display_name": "Internal Search",
        "description": "The Search Action allows the Assistant to search through connected knowledge to help build an answer.",
        "in_code_tool_id": "SearchTool",
    },
    {
        "name": "ImageGenerationTool",
        "display_name": "Image Generation",
        "description": (
            "The Image Generation Action allows the assistant to use DALL-E 3 or GPT-IMAGE-1 to generate images. "
            "The action will be used when the user asks the assistant to generate an image."
        ),
        "in_code_tool_id": "ImageGenerationTool",
    },
    {
        "name": "WebSearchTool",
        "display_name": "Web Search",
        "description": (
            "The Web Search Action allows the assistant "
            "to perform internet searches for up-to-date information."
        ),
        "in_code_tool_id": "WebSearchTool",
    },
    {
        "name": "KnowledgeGraphTool",
        "display_name": "Knowledge Graph Search",
        "description": (
            "The Knowledge Graph Search Action allows the assistant to search the "
            "Knowledge Graph for information. This tool can (for now) only be active in the KG Beta Assistant, "
            "and it requires the Knowledge Graph to be enabled."
        ),
        "in_code_tool_id": "KnowledgeGraphTool",
    },
    {
        "name": "OktaProfileTool",
        "display_name": "Okta Profile",
        "description": (
            "The Okta Profile Action allows the assistant to fetch the current user's information from Okta. "
            "This may include the user's name, email, phone number, address, and other details such as their "
            "manager and direct reports."
        ),
        "in_code_tool_id": "OktaProfileTool",
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # Start transaction
    conn.execute(sa.text("BEGIN"))

    try:
        # Get existing tools to check what already exists
        existing_tools = conn.execute(
            sa.text(
                "SELECT in_code_tool_id FROM tool WHERE in_code_tool_id IS NOT NULL"
            )
        ).fetchall()
        existing_tool_ids = {row[0] for row in existing_tools}

        # Insert or update built-in tools
        for tool in BUILT_IN_TOOLS:
            in_code_id = tool["in_code_tool_id"]

            # Handle historical rename: InternetSearchTool -> WebSearchTool
            if (
                in_code_id == "WebSearchTool"
                and "WebSearchTool" not in existing_tool_ids
                and "InternetSearchTool" in existing_tool_ids
            ):
                # Rename the existing InternetSearchTool row in place and update fields
                conn.execute(
                    sa.text(
                        """
                        UPDATE tool
                        SET name = :name,
                            display_name = :display_name,
                            description = :description,
                            in_code_tool_id = :in_code_tool_id
                        WHERE in_code_tool_id = 'InternetSearchTool'
                        """
                    ),
                    tool,
                )
                # Keep the local view of existing ids in sync to avoid duplicate insert
                existing_tool_ids.discard("InternetSearchTool")
                existing_tool_ids.add("WebSearchTool")
                continue

            if in_code_id in existing_tool_ids:
                # Update existing tool
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
                    tool,
                )
            else:
                # Insert new tool
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO tool (name, display_name, description, in_code_tool_id)
                        VALUES (:name, :display_name, :description, :in_code_tool_id)
                        """
                    ),
                    tool,
                )

        # Commit transaction
        conn.execute(sa.text("COMMIT"))

    except Exception as e:
        # Rollback on error
        conn.execute(sa.text("ROLLBACK"))
        raise e


def downgrade() -> None:
    # We don't remove the tools on downgrade since it's totally fine to just
    # have them around. If we upgrade again, it will be a no-op.
    pass
