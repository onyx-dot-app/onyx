"""seed FetchUrlTool built-in

Revision ID: 92b047e96c9f
Revises: 64bd5677aeb6
Create Date: 2025-09-30 11:08:57.275447

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "92b047e96c9f"
down_revision = "64bd5677aeb6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Keep consistent style with other tool seed migrations
    TOOL_ROW = {
        "name": "FetchUrlTool",
        "display_name": "Fetch Document/URL",
        "description": (
            "Fetch content from documents or URLs. Use fetch_url when the user provides a direct URL "
            "in their message. Use fetch_single_file when the user asks for documents by name/description. "
            "Examples: 'What's on https://reddit.com/r/news?' → use fetch_url. "
            "'Find me the slack bot design doc' → use fetch_single_file. "
            "'Show me DAN-1919' → use fetch_single_file. "
            "'Check www.example.com' → use fetch_url. "
            "Works with web pages, Google Drive links, Slack threads, Notion pages, Reddit posts, "
            "Linear tickets, and any other URL or indexed document."
            "IMPORTANT: If fetch_single_file finds relevant documents, STOP and provide results. "
            "Do NOT call additional search tools. "
        ),
        "in_code_tool_id": "FetchUrlTool",
    }

    conn.execute(sa.text("BEGIN"))
    try:
        existing = conn.execute(
            sa.text(
                """
                SELECT 1 FROM tool WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            {"in_code_tool_id": TOOL_ROW["in_code_tool_id"]},
        ).fetchone()

        if existing:
            # Update the existing row to ensure latest name/description/display_name
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
                TOOL_ROW,
            )
        else:
            # Insert new row
            conn.execute(
                sa.text(
                    """
                    INSERT INTO tool (name, display_name, description, in_code_tool_id)
                    VALUES (:name, :display_name, :description, :in_code_tool_id)
                    """
                ),
                TOOL_ROW,
            )

        conn.execute(sa.text("COMMIT"))
    except Exception:
        conn.execute(sa.text("ROLLBACK"))
        raise


def downgrade() -> None:
    # Do not delete tools on downgrade to keep environment stable, mirroring existing pattern
    # Leaving as a no-op is consistent with other seed tool migrations
    return
