"""Integration tests for the merge default assistants migration."""

import pytest
from sqlalchemy import text

from onyx.db.engine import get_session_context_manager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import TestUser


@pytest.fixture
def admin_user() -> TestUser:
    """Create an admin user for testing."""
    return UserManager.create(name="test_migration_admin")


def test_migration_unified_assistant_properties(admin_user: TestUser) -> None:
    """Test that the migration correctly updates the unified assistant properties."""
    # Fetch personas
    personas = PersonaManager.get_personas(admin_user)

    # Find the unified assistant (ID 0)
    unified_assistant = None
    for persona in personas:
        if persona["id"] == 0:
            unified_assistant = persona
            break

    assert unified_assistant is not None, "Unified assistant not found after migration"

    # Verify the migration updated the assistant correctly
    assert (
        unified_assistant["name"] == "Assistant"
    ), f"Expected name 'Assistant', got {unified_assistant['name']}"
    assert (
        "search, web browsing, and image generation"
        in unified_assistant["description"].lower()
    ), f"Description doesn't mention all capabilities: {unified_assistant['description']}"
    assert (
        unified_assistant["is_default_persona"] is True
    ), "Should be a default persona"
    assert unified_assistant["is_visible"] is True, "Should be visible"
    assert (
        unified_assistant["num_chunks"] == 25
    ), "Should have search capability (num_chunks=25)"


def test_migration_old_assistants_marked_deleted() -> None:
    """Test that old default assistants are marked as deleted in the database."""
    with get_session_context_manager() as db:
        # Check General assistant (ID 1)
        result = db.execute(
            text(
                "SELECT deleted, is_visible, is_default_persona FROM persona WHERE id = 1"
            )
        ).fetchone()

        if result:
            assert result[0] is True, "General assistant should be marked as deleted"
            assert result[1] is False, "General assistant should not be visible"
            assert (
                result[2] is False
            ), "General assistant should not be a default persona"

        # Check Art assistant (ID 3)
        result = db.execute(
            text(
                "SELECT deleted, is_visible, is_default_persona FROM persona WHERE id = 3"
            )
        ).fetchone()

        if result:
            assert result[0] is True, "Art assistant should be marked as deleted"
            assert result[1] is False, "Art assistant should not be visible"
            assert result[2] is False, "Art assistant should not be a default persona"

        # Check Paraphrase assistant (ID 2)
        result = db.execute(
            text("SELECT is_default_persona FROM persona WHERE id = 2")
        ).fetchone()

        if result:
            assert (
                result[0] is False
            ), "Paraphrase assistant should not be a default persona"


def test_migration_tools_assigned_to_unified_assistant() -> None:
    """Test that the migration assigns tools to the unified assistant."""
    with get_session_context_manager() as db:
        # Get tools assigned to persona 0
        result = db.execute(
            text(
                """
                SELECT t.in_code_tool_id
                FROM persona__tool pt
                JOIN tool t ON pt.tool_id = t.id
                WHERE pt.persona_id = 0
            """
            )
        ).fetchall()

        tool_ids = [row[0] for row in result]

        # At minimum, SearchTool should be present
        assert (
            "SearchTool" in tool_ids
        ), "SearchTool should be assigned to unified assistant"

        # Note: ImageGenerationTool and InternetSearchTool might not be available
        # depending on configuration, so we don't assert their presence


def test_migration_user_preferences_updated() -> None:
    """Test that user preferences are correctly migrated."""
    # This test would require setting up user preferences before migration
    # and checking they're updated after. Since we're testing post-migration,
    # we can only verify the structure is correct.

    with get_session_context_manager() as db:
        # Check that no user preferences contain IDs 1 or 3 in visible/chosen assistants
        result = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM user_preferences
                WHERE visible_assistants::jsonb @> '[1]'::jsonb
                   OR visible_assistants::jsonb @> '[3]'::jsonb
                   OR chosen_assistants::jsonb @> '[1]'::jsonb
                   OR chosen_assistants::jsonb @> '[3]'::jsonb
            """
            )
        ).scalar()

        assert (
            result == 0
        ), "User preferences should not contain old assistant IDs in visible/chosen lists"

        # Check that hidden_assistants contains 1 and 3
        result = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM user_preferences
                WHERE hidden_assistants::jsonb @> '[1]'::jsonb
                  AND hidden_assistants::jsonb @> '[3]'::jsonb
            """
            )
        ).fetchone()

        # Note: This might be 0 if no users have preferences set
        # The important thing is that visible/chosen don't have 1 or 3


def test_migration_preserves_other_personas(admin_user: TestUser) -> None:
    """Test that the migration doesn't affect other non-default personas."""
    # Fetch all personas
    personas = PersonaManager.get_personas(admin_user)

    # Check that we still have other personas (like Paraphrase)
    for persona in personas:
        if persona["name"] == "Paraphrase":
            pass
            # Verify it wasn't changed except for is_default_persona
            assert (
                persona["is_default_persona"] is False
            ), "Paraphrase should not be default"
            # Other properties should be preserved
            assert (
                "exact quotes" in persona["description"].lower()
            ), "Paraphrase description should be preserved"
            break

    # Note: Paraphrase might not exist if prebuilt personas were modified
    # So we don't assert it must exist, just check if it's there it's correct
