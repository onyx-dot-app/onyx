"""
Integration tests for the LLM provider listing cache.

The listing endpoints are memoized in Redis (see
onyx/server/manage/llm/provider_cache.py) with a long TTL, so mutations that
change the payload must invalidate explicitly for edits to show up promptly.
"""

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def _get_persona_default_text(user: DATestUser, persona_id: int) -> dict | None:
    response = client.get(
        f"{API_SERVER_URL}/llm/persona/{persona_id}/providers",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()["default_text"]


def test_persona_default_model_edit_invalidates_listing_cache(
    new_admin_user: DATestUser,
) -> None:
    """A persona default-model edit must be visible on the very next listing
    read; the cached entry filled by the first read may not be served stale."""
    provider_a = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        api_key="test-key",
        default_model_name="gpt-4o-mini",
        set_as_default=True,
    )
    provider_b = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        api_key="test-key",
        default_model_name="gpt-4o",
        set_as_default=False,
    )

    persona = PersonaManager.create(
        user_performing_action=new_admin_user,
        default_model_configuration_id=provider_a.model_configuration_ids[0],
    )

    # Fills the cache for this (persona, user) key.
    default_text = _get_persona_default_text(new_admin_user, persona.id)
    assert default_text is not None
    assert default_text["provider_id"] == provider_a.id
    assert default_text["model_name"] == "gpt-4o-mini"

    PersonaManager.edit(
        persona=persona,
        user_performing_action=new_admin_user,
        default_model_configuration_id=provider_b.model_configuration_ids[0],
    )

    default_text = _get_persona_default_text(new_admin_user, persona.id)
    assert default_text is not None
    assert default_text["provider_id"] == provider_b.id
    assert default_text["model_name"] == "gpt-4o"
