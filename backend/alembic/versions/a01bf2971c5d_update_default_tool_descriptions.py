"""update_default_tool_descriptions

Revision ID: a01bf2971c5d
Revises: 87c52ec39f84
Create Date: 2025-12-16 15:21:25.656375

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a01bf2971c5d"
down_revision = "87c52ec39f84"
branch_labels = None
depends_on = None

# new tool descriptions (12/2025)
TOOL_DESCRIPTIONS = {
    "SearchTool": "The Search Action allows the agent to search through connected knowledge to help build an answer.",
    "ImageGenerationTool": (
        "The Image Generation Action allows the agent to use DALL-E 3 or GPT-IMAGE-1 to generate images. "
        "The action will be used when the user asks the agent to generate an image."
    ),
    "WebSearchTool": (
        "The Web Search Action allows the agent "
        "to perform internet searches for up-to-date information."
    ),
    "KnowledgeGraphTool": (
        "The Knowledge Graph Search Action allows the agent to search the "
        "Knowledge Graph for information. This tool can (for now) only be active in the KG Beta Agent, "
        "and it requires the Knowledge Graph to be enabled."
    ),
    "OktaProfileTool": (
        "The Okta Profile Action allows the agent to fetch the current user's information from Okta. "
        "This may include the user's name, email, phone number, address, and other details such as their "
        "manager and direct reports."
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("BEGIN"))

    try:
        for tool_id, description in TOOL_DESCRIPTIONS.items():
            conn.execute(
                sa.text(
                    "UPDATE tool SET description = :description WHERE in_code_tool_id = :tool_id"
                ),
                {"description": description, "tool_id": tool_id},
            )
        conn.execute(sa.text("COMMIT"))
    except Exception as e:
        conn.execute(sa.text("ROLLBACK"))
        raise e


def downgrade() -> None:
    pass
