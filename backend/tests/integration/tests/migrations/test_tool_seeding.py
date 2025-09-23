from sqlalchemy import text

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.reset import downgrade_postgres
from tests.integration.common_utils.reset import upgrade_postgres


def test_tool_seeding_migration() -> None:
    """Test that migration from base to head correctly seeds builtin tools."""
    # Start from base and upgrade to just before tool seeding
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="b7ec9b5b505f",  # Revision before tool seeding
    )

    # Verify no tools exist yet
    with get_session_with_current_tenant() as db_session:
        result = db_session.execute(text("SELECT COUNT(*) FROM tool"))
        count = result.scalar()
        assert count == 0, "No tools should exist before migration"

    # Upgrade to head
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="head",
    )

    # Verify tools were created
    with get_session_with_current_tenant() as db_session:
        result = db_session.execute(
            text(
                """
                SELECT id, name, display_name, description, in_code_tool_id,
                       user_id
                FROM tool
                ORDER BY id
                """
            )
        )
        tools = result.fetchall()

        # Should have all 5 builtin tools
        assert (
            len(tools) == 5
        ), f"Should have created exactly 5 builtin tools, got {len(tools)}"

        # Check SearchTool
        search_tool = next((t for t in tools if t[1] == "SearchTool"), None)
        assert search_tool is not None, "SearchTool should exist"
        assert (
            search_tool[2] == "Internal Search"
        ), "SearchTool display name should be 'Internal Search'"
        assert search_tool[5] is None, "SearchTool should not have a user_id (builtin)"

        # Check ImageGenerationTool
        img_tool = next((t for t in tools if t[1] == "ImageGenerationTool"), None)
        assert img_tool is not None, "ImageGenerationTool should exist"
        assert (
            img_tool[2] == "Image Generation"
        ), "ImageGenerationTool display name should be 'Image Generation'"
        assert (
            img_tool[5] is None
        ), "ImageGenerationTool should not have a user_id (builtin)"

        # Check WebSearchTool
        web_tool = next((t for t in tools if t[1] == "WebSearchTool"), None)
        assert web_tool is not None, "WebSearchTool should exist"
        assert (
            web_tool[2] == "Web Search"
        ), "WebSearchTool display name should be 'Web Search'"
        assert web_tool[5] is None, "WebSearchTool should not have a user_id (builtin)"

        # Check KnowledgeGraphTool
        kg_tool = next((t for t in tools if t[1] == "KnowledgeGraphTool"), None)
        assert kg_tool is not None, "KnowledgeGraphTool should exist"
        assert (
            kg_tool[2] == "Knowledge Graph Search"
        ), "KnowledgeGraphTool display name should be 'Knowledge Graph Search'"
        assert (
            kg_tool[5] is None
        ), "KnowledgeGraphTool should not have a user_id (builtin)"

        # Check OktaProfileTool
        okta_tool = next((t for t in tools if t[1] == "OktaProfileTool"), None)
        assert okta_tool is not None, "OktaProfileTool should exist"
        assert (
            okta_tool[2] == "Okta Profile"
        ), "OktaProfileTool display name should be 'Okta Profile'"
        assert (
            okta_tool[5] is None
        ), "OktaProfileTool should not have a user_id (builtin)"
