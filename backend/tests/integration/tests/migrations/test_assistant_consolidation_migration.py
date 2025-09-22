"""
Integration tests for the assistant consolidation migration.

Tests the migration from multiple default assistants (Search, General, Art, etc.)
to a single default Assistant (ID 0) and the associated tool seeding.
"""

from typing import cast

import pytest
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

        # Should have exactly 3 tools
        assert (
            len(tool_associations) == 3
        ), f"Default assistant should have exactly 3 tools attached, got {len(tool_associations)}"


@pytest.mark.skip(
    reason="Migration test no longer needed - migration has been applied to production"
)
def test_assistant_consolidation_end_state() -> None:
    """Test the end state after the consolidation migration."""
    # Start from base and upgrade to the consolidation migration
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="505c488f6662",  # Assistant consolidation migration
    )

    with get_session_with_current_tenant() as db_session:
        # Check default assistant exists and has correct properties
        result = db_session.execute(
            text(
                """
                SELECT id, name, description, deleted, builtin_persona, is_default_persona
                FROM persona
                WHERE id = 0
                """
            )
        )
        default = result.fetchone()
        assert default is not None, "Default assistant should exist"
        assert default[1] == "Assistant", "Should be named 'Assistant'"
        assert default[3] is False, "Default assistant should not be deleted"
        assert default[4] is True, "Default assistant should be builtin"
        assert default[5] is True, "Default assistant should be default"

        # Check that no other builtin assistants exist that aren't deleted
        result = db_session.execute(
            text(
                """
                SELECT id, name, deleted
                FROM persona
                WHERE builtin_persona = true AND id != 0
                ORDER BY id
                """
            )
        )
        other_builtins = result.fetchall()

        # Any other builtin assistants should be marked as deleted
        for assistant in other_builtins:
            if assistant[0] < 0:  # Negative IDs are old builtin assistants
                assert (
                    assistant[2] is True
                ), f"Old builtin assistant {assistant[1]} (ID {assistant[0]}) should be deleted"

        # Check tools are associated with the default assistant
        result = db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM persona__tool
                WHERE persona_id = 0
                """
            )
        )
        tool_count = cast(int, result.scalar())
        assert tool_count == 3, "Default assistant should have exactly 3 tools"


@pytest.mark.skip(
    reason="Migration test no longer needed - migration has been applied to production"
)
def test_chat_sessions_migration() -> None:
    """Test that existing chat sessions are properly migrated to the default assistant."""
    # Start from base and upgrade to after consolidation
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )

    # First upgrade to the point where we have tools but before consolidation
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="d09fc20a3c66",  # After tool seeding
    )

    # Manually create some builtin assistants and chat sessions to simulate pre-migration state
    with get_session_with_current_tenant() as db_session:
        # Check if persona 0 already exists (it might be created by the migration)
        existing = db_session.execute(
            text("SELECT id FROM persona WHERE id = 0")
        ).fetchone()

        if not existing:
            # Create the Search assistant (ID 0) that will become the unified assistant
            db_session.execute(
                text(
                    """
                    INSERT INTO persona (
                        id, name, description, system_prompt, task_prompt,
                        datetime_aware, is_public, deleted, builtin_persona, is_default_persona,
                        llm_relevance_filter, llm_filter_extraction, recency_bias,
                        is_visible, chunks_above, chunks_below
                    ) VALUES (
                        0, 'Search', 'Search assistant',
                        'You are a search assistant', 'Search for information',
                        false, true, false, true, false,
                        true, true, 'auto', true, 5, 5
                    )
                    """
                )
            )

        # Create other builtin assistants that will be consolidated
        db_session.execute(
            text(
                """
                INSERT INTO persona (
                    id, name, description, system_prompt, task_prompt,
                    datetime_aware, is_public, deleted, builtin_persona, is_default_persona,
                    llm_relevance_filter, llm_filter_extraction, recency_bias,
                    is_visible, chunks_above, chunks_below
                ) VALUES
                    (-1, 'General', 'General assistant',
                     'You are a general assistant', 'Help with general tasks',
                     false, true, false, true, true,
                     false, false, 'auto', true, 5, 5),
                    (-3, 'Art', 'Art generation assistant',
                     'You are an art assistant', 'Generate art',
                     false, true, false, true, false,
                     false, false, 'auto', true, 5, 5)
                """
            )
        )

        # Create a custom assistant (should not be affected)
        db_session.execute(
            text(
                """
                INSERT INTO persona (
                    id, name, description, system_prompt, task_prompt,
                    datetime_aware, is_public, deleted, builtin_persona, is_default_persona,
                    llm_relevance_filter, llm_filter_extraction, recency_bias,
                    is_visible, chunks_above, chunks_below
                ) VALUES (
                    100, 'Custom Assistant', 'User created assistant',
                    'You are a custom assistant', 'Assist with custom tasks',
                    false, true, false, false, false,
                    true, true, 'auto', true, 5, 5
                )
                """
            )
        )

        # Create chat sessions for each assistant
        db_session.execute(
            text(
                """
                INSERT INTO chat_session (
                    id, persona_id, description, deleted, user_id, shared_status, onyxbot_flow
                ) VALUES
                    ('10010000-0000-0000-0000-000000000000'::uuid, 0, 'Search session', false, null, 'private', false),
                    ('10020000-0000-0000-0000-000000000000'::uuid, -1, 'General session', false, null, 'private', false),
                    ('10030000-0000-0000-0000-000000000000'::uuid, -3, 'Art session', false, null, 'private', false),
                    ('10040000-0000-0000-0000-000000000000'::uuid, 100, 'Custom session', false, null, 'private', false)
                """
            )
        )

        db_session.commit()

    # Run the consolidation migration
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="505c488f6662",  # Assistant consolidation migration
    )

    # Verify chat sessions were migrated correctly
    with get_session_with_current_tenant() as db_session:
        result = db_session.execute(
            text(
                """
                SELECT id, persona_id, description
                FROM chat_session
                WHERE id IN ('10010000-0000-0000-0000-000000000000'::uuid,
                             '10020000-0000-0000-0000-000000000000'::uuid,
                             '10030000-0000-0000-0000-000000000000'::uuid,
                             '10040000-0000-0000-0000-000000000000'::uuid)
                ORDER BY id
                """
            )
        )
        sessions = result.fetchall()

        # All builtin assistant sessions should now use the default assistant (ID 0)
        assert sessions[0][1] == 0, "Search session should remain with ID 0"
        assert sessions[1][1] == 0, "General session should be migrated to ID 0"
        assert sessions[2][1] == 0, "Art session should be migrated to ID 0"

        # Custom assistant session should remain unchanged
        assert (
            sessions[3][1] == 100
        ), "Custom assistant session should remain with ID 100"


@pytest.mark.skip(
    reason="Migration test no longer needed - migration has been applied to production"
)
def test_user_preferences_cleanup() -> None:
    """Test that user preferences are cleaned up correctly during migration."""
    # Start from base and upgrade to after tool seeding
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="d09fc20a3c66",  # After tool seeding
    )

    # Create test data
    with get_session_with_current_tenant() as db_session:
        # Check if persona 0 already exists
        existing = db_session.execute(
            text("SELECT id FROM persona WHERE id = 0")
        ).fetchone()

        # Create builtin assistants (skip ID 0 if it already exists)
        if existing:
            # Only create the other builtin assistants
            db_session.execute(
                text(
                    """
                    INSERT INTO persona (
                        id, name, description, system_prompt, task_prompt,
                        datetime_aware, is_public, deleted, builtin_persona, is_default_persona,
                        llm_relevance_filter, llm_filter_extraction, recency_bias,
                        is_visible, chunks_above, chunks_below
                    ) VALUES
                        (-1, 'General', 'General assistant',
                         'You are a general assistant', 'Help with general tasks',
                         false, true, false, true, true,
                         false, false, 'auto', true, 5, 5),
                        (-3, 'Art', 'Art generation assistant',
                         'You are an art assistant', 'Generate art',
                         false, true, false, true, false,
                         false, false, 'auto', true, 5, 5),
                        (100, 'Custom Assistant', 'User created assistant',
                         'You are a custom assistant', 'Assist with custom tasks',
                         false, true, false, false, false,
                         true, true, 'auto', true, 5, 5)
                    """
                )
            )
        else:
            # Create all assistants including ID 0
            db_session.execute(
                text(
                    """
                    INSERT INTO persona (
                        id, name, description, system_prompt, task_prompt,
                        datetime_aware, is_public, deleted, builtin_persona, is_default_persona,
                        llm_relevance_filter, llm_filter_extraction, recency_bias,
                        is_visible, chunks_above, chunks_below
                    ) VALUES
                        (0, 'Search', 'Search assistant',
                         'You are a search assistant', 'Search for information',
                         false, true, false, true, false,
                         true, true, 'auto', true, 5, 5),
                        (-1, 'General', 'General assistant',
                         'You are a general assistant', 'Help with general tasks',
                         false, true, false, true, true,
                         false, false, 'auto', true, 5, 5),
                        (-3, 'Art', 'Art generation assistant',
                         'You are an art assistant', 'Generate art',
                         false, true, false, true, false,
                         false, false, 'auto', true, 5, 5),
                        (100, 'Custom Assistant', 'User created assistant',
                         'You are a custom assistant', 'Assist with custom tasks',
                         false, true, false, false, false,
                         true, true, 'auto', true, 5, 5)
                    """
                )
            )

        # Create test users with preferences (all in user table)
        db_session.execute(
            text(
                """
                INSERT INTO "user" (
                    id, email, hashed_password, is_active, is_superuser, is_verified, role,
                    chosen_assistants, visible_assistants, hidden_assistants, pinned_assistants
                )
                VALUES
                    ('11111111-1111-1111-1111-111111111111'::uuid, 'user1@test.com', 'dummy_hash',
                     true, false, true, 'basic',
                     '[0, -1, -3, 100]'::jsonb, '[0, -1, -3, 100]'::jsonb, '[]'::jsonb, '[0, -1]'::jsonb),
                    ('22222222-2222-2222-2222-222222222222'::uuid, 'user2@test.com', 'dummy_hash',
                     true, false, true, 'basic',
                     '[-1, -3]'::jsonb, '[-1, -3, 100]'::jsonb, '[0]'::jsonb, '[-3]'::jsonb)
                """
            )
        )

        db_session.commit()

    # Run the consolidation migration
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="505c488f6662",  # Assistant consolidation migration
    )

    # Verify user preferences were cleaned up
    with get_session_with_current_tenant() as db_session:
        # Check user 1 preferences
        result = db_session.execute(
            text(
                """
                SELECT chosen_assistants, visible_assistants,
                       hidden_assistants, pinned_assistants
                FROM "user"
                WHERE id = '11111111-1111-1111-1111-111111111111'::uuid
                """
            )
        )
        user1_prefs = result.fetchone()
        if user1_prefs:
            # JSONB columns are already deserialized as Python objects
            chosen = user1_prefs[0] if user1_prefs[0] else []
            visible = user1_prefs[1] if user1_prefs[1] else []
            hidden = user1_prefs[2] if user1_prefs[2] else []
            pinned = user1_prefs[3] if user1_prefs[3] else []

            # Old builtin assistants (-1, -3) should be removed from active preferences
            assert (
                -1 not in chosen
            ), "General assistant (-1) should be removed from chosen"
            assert -3 not in chosen, "Art assistant (-3) should be removed from chosen"
            assert (
                -1 not in visible
            ), "General assistant (-1) should be removed from visible"
            assert (
                -3 not in visible
            ), "Art assistant (-3) should be removed from visible"
            assert (
                -1 not in pinned
            ), "General assistant (-1) should be removed from pinned"
            assert -3 not in pinned, "Art assistant (-3) should be removed from pinned"

            # Default assistant (0) and custom (100) should remain
            assert 0 in chosen or 0 in visible, "Default assistant (0) should remain"
            assert (
                100 in chosen or 100 in visible
            ), "Custom assistant (100) should remain"

            # Deleted assistants should be in hidden
            assert -1 in hidden, "General assistant (-1) should be in hidden"
            assert -3 in hidden, "Art assistant (-3) should be in hidden"

        # Check user 2 preferences
        result = db_session.execute(
            text(
                """
                SELECT chosen_assistants, visible_assistants,
                       hidden_assistants, pinned_assistants
                FROM "user"
                WHERE id = '22222222-2222-2222-2222-222222222222'::uuid
                """
            )
        )
        user2_prefs = result.fetchone()
        if user2_prefs:
            # JSONB columns are already deserialized as Python objects
            chosen = user2_prefs[0] if user2_prefs[0] else []
            visible = user2_prefs[1] if user2_prefs[1] else []
            hidden = user2_prefs[2] if user2_prefs[2] else []
            pinned = user2_prefs[3] if user2_prefs[3] else []

            # Old builtin assistants should be removed
            assert (
                -1 not in chosen
            ), "General assistant (-1) should be removed from chosen"
            assert -3 not in chosen, "Art assistant (-3) should be removed from chosen"
            assert -3 not in pinned, "Art assistant (-3) should be removed from pinned"

            # Custom assistant should remain
            assert (
                100 in visible or 100 in chosen
            ), "Custom assistant (100) should remain"

            # Deleted assistants and originally hidden (0) should be in hidden
            assert -1 in hidden, "General assistant (-1) should be in hidden"
            assert -3 in hidden, "Art assistant (-3) should be in hidden"
            assert (
                0 in hidden
            ), "Default assistant (0) should remain in hidden as it was before"


@pytest.mark.skip(
    reason="Migration test no longer needed - migration has been applied to production"
)
def test_migration_creates_custom_personas_correctly() -> None:
    """Test that the migration doesn't affect custom personas."""
    # Start from base and upgrade
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="d09fc20a3c66",  # After tool seeding, before consolidation
    )

    # Create a custom persona
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            text(
                """
                INSERT INTO persona (
                    id, name, description, system_prompt, task_prompt,
                    datetime_aware, is_public, deleted, builtin_persona, is_default_persona,
                    llm_relevance_filter, llm_filter_extraction, recency_bias,
                    is_visible, chunks_above, chunks_below
                ) VALUES (
                    100, 'Custom Assistant', 'User created assistant',
                    'You are a custom assistant', 'Assist with custom tasks',
                    false, true, false, false, false,
                    true, true, 'auto', true, 5, 5
                )
                """
            )
        )
        db_session.commit()

    # Run the consolidation migration
    upgrade_postgres(
        database="postgres",
        config_name="alembic",
        revision="505c488f6662",  # Consolidation migration
    )

    # Verify custom persona is unchanged
    with get_session_with_current_tenant() as db_session:
        result = db_session.execute(
            text(
                """
                SELECT id, name, deleted, builtin_persona
                FROM persona
                WHERE id = 100
                """
            )
        )
        custom = result.fetchone()
        assert custom is not None, "Custom assistant should still exist"
        assert (
            custom[1] == "Custom Assistant"
        ), "Custom assistant name should be unchanged"
        assert custom[2] is False, "Custom assistant should not be deleted"
        assert custom[3] is False, "Custom assistant should not be builtin"
