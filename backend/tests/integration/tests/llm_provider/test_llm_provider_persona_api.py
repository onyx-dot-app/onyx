"""Integration tests for LLM provider persona RBAC API layer.

Tests the API endpoints added in PR4 for handling persona relationships.
"""

from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def test_create_llm_provider_with_persona_restrictions_via_api(
    admin_user: DATestUser, reset: None
) -> None:
    """Test creating an LLM provider with persona restrictions via API."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1_api",
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2_api",
        user_performing_action=admin_user,
    )

    # Create LLM provider with persona restrictions
    provider = LLMProviderManager.create(
        name="provider-with-personas-api",
        is_public=False,
        personas=[persona1.id, persona2.id],
        user_performing_action=admin_user,
    )

    # Verify provider was created with personas
    assert provider.personas is not None
    assert len(provider.personas) == 2
    assert persona1.id in provider.personas
    assert persona2.id in provider.personas
    assert not provider.is_public


def test_update_llm_provider_persona_restrictions(
    admin_user: DATestUser, reset: None
) -> None:
    """Test updating an LLM provider's persona restrictions."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1_update",
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2_update",
        user_performing_action=admin_user,
    )
    persona3 = PersonaManager.create(
        name="persona3_update",
        user_performing_action=admin_user,
    )

    # Create provider with initial personas
    provider = LLMProviderManager.create(
        name="provider-update-personas",
        is_public=False,
        personas=[persona1.id, persona2.id],
        user_performing_action=admin_user,
    )

    assert len(provider.personas) == 2
    assert persona1.id in provider.personas
    assert persona2.id in provider.personas

    # Update to different personas
    updated_provider = LLMProviderManager.create(
        name=provider.name,  # Same name to trigger update
        is_public=False,
        personas=[persona3.id],
        user_performing_action=admin_user,
    )

    # Verify personas were updated
    assert len(updated_provider.personas) == 1
    assert persona3.id in updated_provider.personas
    assert persona1.id not in updated_provider.personas
    assert persona2.id not in updated_provider.personas


def test_create_persona_with_exclude_public_providers_via_api(
    admin_user: DATestUser, reset: None
) -> None:
    """Test creating a persona with exclude_public_providers via API."""
    # Create persona with exclude_public_providers=True
    persona = PersonaManager.create(
        name="persona_exclude_public",
        exclude_public_providers=True,
        user_performing_action=admin_user,
    )

    # The persona should be created successfully
    assert persona is not None
    assert persona.name == "persona_exclude_public"


def test_create_llm_provider_public_with_personas(
    admin_user: DATestUser, reset: None
) -> None:
    """Test that public providers can still have persona restrictions."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1_public_provider",
        user_performing_action=admin_user,
    )

    # Create a PUBLIC provider with persona restrictions
    # (Public override means everyone has access regardless of persona restrictions)
    provider = LLMProviderManager.create(
        name="public-provider-with-personas",
        is_public=True,
        personas=[persona1.id],
        user_performing_action=admin_user,
    )

    # Verify provider was created
    assert provider.is_public
    assert len(provider.personas) == 1
    assert persona1.id in provider.personas


def test_llm_provider_api_returns_personas_field(
    admin_user: DATestUser, reset: None
) -> None:
    """Test that GET /admin/llm/provider returns personas field."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1_get_api",
        user_performing_action=admin_user,
    )
    persona2 = PersonaManager.create(
        name="persona2_get_api",
        user_performing_action=admin_user,
    )

    # Create provider with personas
    provider = LLMProviderManager.create(
        name="provider-get-test",
        is_public=False,
        personas=[persona1.id, persona2.id],
        user_performing_action=admin_user,
    )

    # Get all providers
    all_providers = LLMProviderManager.get_all(user_performing_action=admin_user)

    # Find our provider
    our_provider = next((p for p in all_providers if p.id == provider.id), None)
    assert our_provider is not None
    assert len(our_provider.personas) == 2
    assert persona1.id in our_provider.personas
    assert persona2.id in our_provider.personas


def test_delete_llm_provider_with_personas(admin_user: DATestUser, reset: None) -> None:
    """Test deleting an LLM provider that has persona restrictions."""
    # Create personas
    persona1 = PersonaManager.create(
        name="persona1_delete",
        user_performing_action=admin_user,
    )

    # Create provider with personas
    provider = LLMProviderManager.create(
        name="provider-delete-test",
        is_public=False,
        personas=[persona1.id],
        user_performing_action=admin_user,
    )

    # Delete the provider
    LLMProviderManager.delete(provider, user_performing_action=admin_user)

    # Verify provider was deleted
    LLMProviderManager.verify(
        provider, verify_deleted=True, user_performing_action=admin_user
    )
