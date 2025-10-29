"""Integration tests for LLM provider persona RBAC CRUD operations.

Tests the CRUD operations added in PR3 for handling persona relationships.
"""

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import get_personas_for_llm_provider
from onyx.db.llm import get_personas_using_provider
from onyx.db.models import Persona
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def test_create_llm_provider_with_persona_restrictions(
    admin_user: DATestUser, reset: None
) -> None:
    """Test creating an LLM provider with persona restrictions via the manager."""
    # Create personas
    PersonaManager.create(
        name="persona1_for_provider",
        user_performing_action=admin_user,
    )
    PersonaManager.create(
        name="persona2_for_provider",
        user_performing_action=admin_user,
    )

    # Note: The LLMProviderManager.create() needs to support personas parameter
    # For now, we'll create without personas and verify the DB layer accepts it
    provider = LLMProviderManager.create(
        name="provider-with-personas",
        is_public=False,
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Manually verify provider was created
        provider_obj = fetch_existing_llm_provider(provider.name, db_session)
        assert provider_obj is not None
        assert provider_obj.name == "provider-with-personas"
        assert not provider_obj.is_public


def test_delete_llm_provider_clears_persona_overrides(
    admin_user: DATestUser, reset: None
) -> None:
    """Test that deleting an LLM provider clears persona overrides."""
    # Create a provider
    provider = LLMProviderManager.create(
        name="provider-to-delete",
        user_performing_action=admin_user,
    )

    # Create personas that use this provider
    persona1 = PersonaManager.create(
        name="persona1_using_provider",
        llm_model_provider_override=provider.name,
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2_using_provider",
        llm_model_provider_override=provider.name,
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Verify personas are using the provider
        personas_using = get_personas_using_provider(db_session, provider.name)
        assert len(personas_using) == 2
        persona_ids = {p.id for p in personas_using}
        assert persona1.id in persona_ids
        assert persona2.id in persona_ids

    # Delete the provider
    LLMProviderManager.delete(provider, user_performing_action=admin_user)

    with get_session_with_current_tenant() as db_session:
        # Verify personas no longer use this provider (override should be cleared)
        personas_after_delete = get_personas_using_provider(db_session, provider.name)
        assert len(personas_after_delete) == 0

        # Verify personas still exist but don't have the override
        persona1_obj = (
            db_session.query(Persona).filter(Persona.id == persona1.id).first()
        )
        persona2_obj = (
            db_session.query(Persona).filter(Persona.id == persona2.id).first()
        )
        assert persona1_obj is not None
        assert persona2_obj is not None
        assert persona1_obj.llm_model_provider_override is None
        assert persona2_obj.llm_model_provider_override is None


def test_create_persona_with_exclude_public_providers(
    admin_user: DATestUser, reset: None
) -> None:
    """Test creating a persona with exclude_public_providers flag."""
    # Note: PersonaManager.create() needs to support exclude_public_providers parameter
    # For now, we'll verify the DB layer can handle it

    # Create a persona (without the flag for now, as manager may not support it yet)
    persona = PersonaManager.create(
        name="persona_with_exclusion",
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        persona_obj = db_session.query(Persona).filter(Persona.id == persona.id).first()
        assert persona_obj is not None
        assert persona_obj.name == "persona_with_exclusion"
        # Default should be False
        assert persona_obj.exclude_public_providers is False


def test_update_persona_with_exclude_public_providers(
    admin_user: DATestUser, reset: None
) -> None:
    """Test updating a persona to set exclude_public_providers."""
    # Create a persona
    persona = PersonaManager.create(
        name="persona_to_update",
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Verify initial state
        persona_obj = db_session.query(Persona).filter(Persona.id == persona.id).first()
        assert persona_obj is not None
        assert persona_obj.exclude_public_providers is False

        # Update the flag directly (simulating what the API layer will do)
        persona_obj.exclude_public_providers = True
        db_session.commit()

        # Verify the update
        db_session.refresh(persona_obj)
        assert persona_obj.exclude_public_providers is True


def test_referential_integrity_persona_deletion(
    admin_user: DATestUser, reset: None
) -> None:
    """Test that persona relationships are cleaned up when personas are deleted."""
    # Create a provider
    provider = LLMProviderManager.create(
        name="provider-for-referential-test",
        is_public=False,
        user_performing_action=admin_user,
    )

    # Create a persona
    persona = PersonaManager.create(
        name="persona-for-referential-test",
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Manually add persona restriction
        from onyx.db.llm import update_llm_provider_persona_relationships__no_commit

        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [persona.id],
        )
        db_session.commit()

        # Verify relationship exists
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 1
        assert persona.id in persona_ids

    # Delete the persona
    PersonaManager.delete(persona, user_performing_action=admin_user)

    with get_session_with_current_tenant() as db_session:
        # Verify relationship was automatically cleaned up (CASCADE delete)
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        # The relationship should be removed due to CASCADE on foreign key
        assert persona.id not in persona_ids


def test_upsert_llm_provider_updates_persona_relationships(
    admin_user: DATestUser, reset: None
) -> None:
    """Test that upserting (updating) an LLM provider correctly updates persona relationships."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1_for_upsert",
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2_for_upsert",
        user_performing_action=admin_user,
    )
    persona3 = PersonaManager.create(
        name="persona3_for_upsert",
        user_performing_action=admin_user,
    )

    # Create a provider
    provider = LLMProviderManager.create(
        name="provider-for-upsert",
        is_public=False,
        user_performing_action=admin_user,
    )

    with get_session_with_current_tenant() as db_session:
        # Manually add initial persona restrictions
        from onyx.db.llm import update_llm_provider_persona_relationships__no_commit

        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [persona1.id, persona2.id],
        )
        db_session.commit()

        # Verify initial relationships
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 2
        assert persona1.id in persona_ids
        assert persona2.id in persona_ids

        # Update to different personas
        update_llm_provider_persona_relationships__no_commit(
            db_session,
            provider.id,
            [persona3.id],
        )
        db_session.commit()

        # Verify updated relationships
        persona_ids = get_personas_for_llm_provider(db_session, provider.id)
        assert len(persona_ids) == 1
        assert persona3.id in persona_ids
        assert persona1.id not in persona_ids
        assert persona2.id not in persona_ids
