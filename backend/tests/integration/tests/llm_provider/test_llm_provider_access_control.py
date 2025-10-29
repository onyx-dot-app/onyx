"""Integration tests for LLM provider persona RBAC DB access layer.

Tests the database access functions added in PR2 for LLM provider access control.
"""

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_user_group_ids
from onyx.db.llm import get_personas_for_llm_provider
from onyx.db.llm import update_llm_provider_persona_relationships__no_commit
from onyx.db.llm import validate_persona_ids_exist
from onyx.db.models import User
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def test_fetch_user_group_ids(admin_user: DATestUser, reset: None) -> None:
    """Test fetching user group IDs for a user."""
    # Create a basic user (not admin)
    basic_user = UserManager.create(name="basic_user_for_groups")

    # Create user groups and add the user to them
    group1 = UserGroupManager.create(
        name="group1",
        user_ids=[basic_user.id],
        user_performing_action=admin_user,
    )
    group2 = UserGroupManager.create(
        name="group2",
        user_ids=[basic_user.id],
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Get the User object from DB
        user_obj = db_session.query(User).filter(User.id == basic_user.id).first()
        assert user_obj is not None

        # Test fetching group IDs
        group_ids = fetch_user_group_ids(db_session, user_obj)

        # Should return both group IDs
        assert len(group_ids) == 2
        assert group1.id in group_ids
        assert group2.id in group_ids

        # Test with None user (anonymous)
        anonymous_group_ids = fetch_user_group_ids(db_session, None)
        assert len(anonymous_group_ids) == 0


def test_validate_persona_ids_exist(admin_user: DATestUser, reset: None) -> None:
    """Test validating that persona IDs exist in the database."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1",
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2",
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Test with all valid IDs
        fetched, missing = validate_persona_ids_exist(
            db_session, [persona1.id, persona2.id]
        )
        assert len(fetched) == 2
        assert persona1.id in fetched
        assert persona2.id in fetched
        assert len(missing) == 0

        # Test with some invalid IDs
        fetched, missing = validate_persona_ids_exist(
            db_session, [persona1.id, 99999, 88888]
        )
        assert len(fetched) == 1
        assert persona1.id in fetched
        assert len(missing) == 2
        assert 99999 in missing
        assert 88888 in missing

        # Test with all invalid IDs
        fetched, missing = validate_persona_ids_exist(db_session, [99999, 88888])
        assert len(fetched) == 0
        assert len(missing) == 2


def test_update_and_get_llm_provider_persona_relationships(
    admin_user: DATestUser, reset: None
) -> None:
    """Test updating and retrieving LLM provider persona relationships."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1",
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2",
        user_performing_action=admin_user,
    )
    persona3 = PersonaManager.create(
        name="persona3",
        user_performing_action=admin_user,
    )

    # Create LLM provider
    provider = LLMProviderManager.create(
        name="test-provider",
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Initially no persona relationships
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 0

        # Add relationships for persona1 and persona2
        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [persona1.id, persona2.id],
        )
        db_session.commit()

        # Verify relationships were added
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 2
        assert persona1.id in persona_ids
        assert persona2.id in persona_ids

        # Update to only persona3
        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [persona3.id],
        )
        db_session.commit()

        # Verify relationships were replaced
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 1
        assert persona3.id in persona_ids

        # Clear all relationships (pass None)
        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            None,
        )
        db_session.commit()

        # Verify all relationships were removed
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 0


def test_can_user_access_llm_provider__public(
    admin_user: DATestUser, reset: None
) -> None:
    """Test access to public LLM providers."""
    # Create a basic user
    basic_user = UserManager.create(name="basic_user_public")

    # Create a public LLM provider
    provider = LLMProviderManager.create(
        name="public-provider",
        is_public=True,
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Get the User object
        user_obj = db_session.query(User).filter(User.id == basic_user.id).first()
        assert user_obj is not None

        # Get provider with relationships loaded
        provider_obj = fetch_existing_llm_provider(provider.name, db_session)
        assert provider_obj is not None

        # Get user group IDs
        user_group_ids = fetch_user_group_ids(db_session, user_obj)

        # Public provider should be accessible by anyone
        assert can_user_access_llm_provider(provider_obj, user_group_ids, None)

        # Even anonymous users (empty group_ids) should have access
        assert can_user_access_llm_provider(provider_obj, set(), None)


def test_can_user_access_llm_provider__group_restrictions(
    admin_user: DATestUser, reset: None
) -> None:
    """Test access to LLM providers with group restrictions only."""
    # Create users
    user_in_group = UserManager.create(name="user_in_group")
    user_not_in_group = UserManager.create(name="user_not_in_group")

    # Create a user group with user_in_group
    group = UserGroupManager.create(
        name="allowed_group",
        user_ids=[user_in_group.id],
        user_performing_action=admin_user,
    )

    # Create a private LLM provider restricted to the group
    provider = LLMProviderManager.create(
        name="group-restricted-provider",
        is_public=False,
        groups=[group.id],
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Get User objects
        user_in_group_obj = (
            db_session.query(User).filter(User.id == user_in_group.id).first()
        )
        user_not_in_group_obj = (
            db_session.query(User).filter(User.id == user_not_in_group.id).first()
        )
        assert user_in_group_obj is not None
        assert user_not_in_group_obj is not None

        # Get provider with relationships loaded
        provider_obj = fetch_existing_llm_provider(provider.name, db_session)
        assert provider_obj is not None

        # User in group should have access
        user_in_group_ids = fetch_user_group_ids(db_session, user_in_group_obj)
        assert can_user_access_llm_provider(provider_obj, user_in_group_ids, None)

        # User not in group should NOT have access
        user_not_in_group_ids = fetch_user_group_ids(db_session, user_not_in_group_obj)
        assert not can_user_access_llm_provider(
            provider_obj, user_not_in_group_ids, None
        )


def test_can_user_access_llm_provider__persona_restrictions(
    admin_user: DATestUser, reset: None
) -> None:
    """Test access to LLM providers with persona restrictions only."""
    # Create personas
    allowed_persona = PersonaManager.create(
        name="allowed_persona",
        user_performing_action=admin_user,
    )
    disallowed_persona = PersonaManager.create(
        name="disallowed_persona",
        user_performing_action=admin_user,
    )

    # Create a user (group membership doesn't matter for persona-only restriction)
    basic_user = UserManager.create(name="basic_user_persona")

    # Create a private LLM provider restricted to allowed_persona
    provider = LLMProviderManager.create(
        name="persona-restricted-provider",
        is_public=False,
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Manually add persona restriction
        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [allowed_persona.id],
        )
        db_session.commit()

        # Get User object
        user_obj = db_session.query(User).filter(User.id == basic_user.id).first()
        assert user_obj is not None

        # Get provider with relationships loaded
        provider_obj = fetch_existing_llm_provider(provider.name, db_session)
        assert provider_obj is not None

        # Get user group IDs
        user_group_ids = fetch_user_group_ids(db_session, user_obj)

        # Get persona objects
        from onyx.db.models import Persona

        allowed_persona_obj = (
            db_session.query(Persona).filter(Persona.id == allowed_persona.id).first()
        )
        disallowed_persona_obj = (
            db_session.query(Persona)
            .filter(Persona.id == disallowed_persona.id)
            .first()
        )
        assert allowed_persona_obj is not None
        assert disallowed_persona_obj is not None

        # Using allowed persona should grant access
        assert can_user_access_llm_provider(
            provider_obj, user_group_ids, allowed_persona_obj
        )

        # Using disallowed persona should deny access
        assert not can_user_access_llm_provider(
            provider_obj, user_group_ids, disallowed_persona_obj
        )

        # Not using any persona should deny access
        assert not can_user_access_llm_provider(provider_obj, user_group_ids, None)


def test_can_user_access_llm_provider__combined_restrictions(
    admin_user: DATestUser, reset: None
) -> None:
    """Test access to LLM providers with BOTH group AND persona restrictions (AND logic)."""
    # Create users
    user_in_group = UserManager.create(name="user_in_group_combined")
    user_not_in_group = UserManager.create(name="user_not_in_group_combined")

    # Create a user group with user_in_group
    group = UserGroupManager.create(
        name="combined_group",
        user_ids=[user_in_group.id],
        user_performing_action=admin_user,
    )

    # Create personas
    allowed_persona = PersonaManager.create(
        name="allowed_persona_combined",
        user_performing_action=admin_user,
    )

    # Create a private LLM provider restricted to BOTH group AND persona
    provider = LLMProviderManager.create(
        name="combined-restricted-provider",
        is_public=False,
        groups=[group.id],
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Add persona restriction
        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [allowed_persona.id],
        )
        db_session.commit()

        # Get User objects
        user_in_group_obj = (
            db_session.query(User).filter(User.id == user_in_group.id).first()
        )
        user_not_in_group_obj = (
            db_session.query(User).filter(User.id == user_not_in_group.id).first()
        )
        assert user_in_group_obj is not None
        assert user_not_in_group_obj is not None

        # Get provider with relationships loaded
        provider_obj = fetch_existing_llm_provider(provider.name, db_session)
        assert provider_obj is not None

        # Get persona object
        from onyx.db.models import Persona

        allowed_persona_obj = (
            db_session.query(Persona).filter(Persona.id == allowed_persona.id).first()
        )
        assert allowed_persona_obj is not None

        # User IN group WITH allowed persona should have access (AND logic satisfied)
        user_in_group_ids = fetch_user_group_ids(db_session, user_in_group_obj)
        assert can_user_access_llm_provider(
            provider_obj, user_in_group_ids, allowed_persona_obj
        )

        # User IN group WITHOUT persona should NOT have access (AND logic not satisfied)
        assert not can_user_access_llm_provider(provider_obj, user_in_group_ids, None)

        # User NOT in group WITH allowed persona should NOT have access (AND logic not satisfied)
        user_not_in_group_ids = fetch_user_group_ids(db_session, user_not_in_group_obj)
        assert not can_user_access_llm_provider(
            provider_obj, user_not_in_group_ids, allowed_persona_obj
        )

        # User NOT in group WITHOUT persona should NOT have access
        assert not can_user_access_llm_provider(
            provider_obj, user_not_in_group_ids, None
        )


def test_can_user_access_llm_provider__locked(
    admin_user: DATestUser, reset: None
) -> None:
    """Test access to locked LLM providers (private with no restrictions)."""
    # Create a user
    basic_user = UserManager.create(name="basic_user_locked")

    # Create a private LLM provider with NO group or persona restrictions
    provider = LLMProviderManager.create(
        name="locked-provider",
        is_public=False,
        groups=[],  # No groups
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Don't add any persona restrictions

        # Get User object
        user_obj = db_session.query(User).filter(User.id == basic_user.id).first()
        assert user_obj is not None

        # Get provider with relationships loaded
        provider_obj = fetch_existing_llm_provider(provider.name, db_session)
        assert provider_obj is not None

        # Get user group IDs
        user_group_ids = fetch_user_group_ids(db_session, user_obj)

        # Locked provider (neither groups nor personas) should be inaccessible
        assert not can_user_access_llm_provider(provider_obj, user_group_ids, None)

        # Even with a persona, should still be inaccessible
        persona = PersonaManager.create(
            name="persona_for_locked",
            user_performing_action=admin_user,
        )
        from onyx.db.models import Persona

        persona_obj = db_session.query(Persona).filter(Persona.id == persona.id).first()
        assert persona_obj is not None

        assert not can_user_access_llm_provider(
            provider_obj, user_group_ids, persona_obj
        )
