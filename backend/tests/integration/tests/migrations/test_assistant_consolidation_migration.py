"""
Integration tests for the assistant consolidation migration.

Tests the migration from multiple default assistants (Search, General, Art, etc.)
to a single default Assistant (ID 0) and the associated tool seeding.
"""

from sqlalchemy import text

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.reset import downgrade_postgres
from tests.integration.common_utils.reset import upgrade_postgres


def test_cold_startup_default_assistant() -> None:
    """Test that cold startup creates only the default assistant."""
    # Start fresh at the head revision
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(database="postgres", config_name="alembic", revision="head")

    with get_session_with_current_tenant() as db_session:
        # Check only default assistant exists
        result = db_session.execute(
            text(
                """
                SELECT id, name, builtin_persona, is_default_persona, deleted
                FROM persona
                WHERE builtin_persona = true
                ORDER BY id
                """
            )
        )
        assistants = result.fetchall()

        # Should have exactly one builtin assistant
        assert len(assistants) == 1, "Should have exactly one builtin assistant"
        default = assistants[0]
        assert default[0] == 0, "Default assistant should have ID 0"
        assert default[1] == "Assistant", "Should be named 'Assistant'"
        assert default[2] is True, "Should be builtin"
        assert default[3] is True, "Should be default"
        assert default[4] is False, "Should not be deleted"

        # Check tools are properly associated
        result = db_session.execute(
            text(
                """
                SELECT t.name, t.display_name
                FROM tool t
                JOIN persona__tool pt ON t.id = pt.tool_id
                WHERE pt.persona_id = 0
                ORDER BY t.name
                """
            )
        )
        tool_associations = result.fetchall()
        tool_names = [row[0] for row in tool_associations]
        tool_display_names = [row[1] for row in tool_associations]

        # Verify all three main tools are attached
        assert (
            "SearchTool" in tool_names
        ), "Default assistant should have SearchTool attached"
        assert (
            "ImageGenerationTool" in tool_names
        ), "Default assistant should have ImageGenerationTool attached"
        assert (
            "WebSearchTool" in tool_names
        ), "Default assistant should have WebSearchTool attached"

        # Also verify by display names for clarity
        assert (
            "Internal Search" in tool_display_names
        ), "Default assistant should have Internal Search tool"
        assert (
            "Image Generation" in tool_display_names
        ), "Default assistant should have Image Generation tool"
        assert (
            "Web Search" in tool_display_names
        ), "Default assistant should have Web Search tool"

        # Should have exactly 4 tools
        assert (
            len(tool_associations) == 4
        ), f"Default assistant should have exactly 4 tools attached, got {len(tool_associations)}"
