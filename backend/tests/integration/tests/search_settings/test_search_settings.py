import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


SEARCH_SETTINGS_URL = f"{API_SERVER_URL}/search-settings"


def _get_current_search_settings(user: DATestUser) -> dict:
    response = requests.get(
        f"{SEARCH_SETTINGS_URL}/get-current-search-settings",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_all_search_settings(user: DATestUser) -> dict:
    response = requests.get(
        f"{SEARCH_SETTINGS_URL}/get-all-search-settings",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_secondary_search_settings(user: DATestUser) -> dict | None:
    response = requests.get(
        f"{SEARCH_SETTINGS_URL}/get-secondary-search-settings",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _update_inference_settings(user: DATestUser, settings: dict) -> None:
    response = requests.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=user.headers,
    )
    response.raise_for_status()


def test_get_current_search_settings(admin_user: DATestUser) -> None:
    """Verify that GET current search settings returns expected fields."""
    settings = _get_current_search_settings(admin_user)

    assert "model_name" in settings
    assert "model_dim" in settings
    assert "enable_contextual_rag" in settings
    assert "contextual_rag_llm_name" in settings
    assert "contextual_rag_llm_provider" in settings
    assert "index_name" in settings
    assert "embedding_precision" in settings


def test_get_all_search_settings(admin_user: DATestUser) -> None:
    """Verify that GET all search settings returns current and secondary."""
    all_settings = _get_all_search_settings(admin_user)

    assert "current_settings" in all_settings
    assert "secondary_settings" in all_settings
    assert all_settings["current_settings"] is not None
    assert "model_name" in all_settings["current_settings"]


def test_get_secondary_search_settings_none_by_default(
    admin_user: DATestUser,
) -> None:
    """Verify that no secondary search settings exist by default."""
    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is None


def test_set_contextual_rag_model(admin_user: DATestUser) -> None:
    """Set contextual RAG LLM model and verify it persists."""
    settings = _get_current_search_settings(admin_user)

    settings["contextual_rag_llm_name"] = "gpt-4o"
    settings["contextual_rag_llm_provider"] = "openai"
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["contextual_rag_llm_name"] == "gpt-4o"
    assert updated["contextual_rag_llm_provider"] == "openai"


def test_unset_contextual_rag_model(admin_user: DATestUser) -> None:
    """Set a contextual RAG model, then unset it and verify it becomes None."""
    settings = _get_current_search_settings(admin_user)
    settings["contextual_rag_llm_name"] = "gpt-4o-mini"
    settings["contextual_rag_llm_provider"] = "openai"
    _update_inference_settings(admin_user, settings)

    # Verify it's set
    updated = _get_current_search_settings(admin_user)
    assert updated["contextual_rag_llm_name"] == "gpt-4o-mini"
    assert updated["contextual_rag_llm_provider"] == "openai"

    # Unset the model
    updated["contextual_rag_llm_name"] = None
    updated["contextual_rag_llm_provider"] = None
    _update_inference_settings(admin_user, updated)

    # Verify it's unset
    final = _get_current_search_settings(admin_user)
    assert final["contextual_rag_llm_name"] is None
    assert final["contextual_rag_llm_provider"] is None


def test_change_contextual_rag_model(admin_user: DATestUser) -> None:
    """Change contextual RAG from one model to another and verify the switch."""
    settings = _get_current_search_settings(admin_user)
    settings["contextual_rag_llm_name"] = "gpt-4o"
    settings["contextual_rag_llm_provider"] = "openai"
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["contextual_rag_llm_name"] == "gpt-4o"
    assert updated["contextual_rag_llm_provider"] == "openai"

    # Switch to a different model and provider
    updated["contextual_rag_llm_name"] = "claude-3-opus"
    updated["contextual_rag_llm_provider"] = "anthropic"
    _update_inference_settings(admin_user, updated)

    final = _get_current_search_settings(admin_user)
    assert final["contextual_rag_llm_name"] == "claude-3-opus"
    assert final["contextual_rag_llm_provider"] == "anthropic"


def test_change_contextual_rag_provider_only(admin_user: DATestUser) -> None:
    """Change only the provider while keeping the same model name."""
    settings = _get_current_search_settings(admin_user)
    settings["contextual_rag_llm_name"] = "gpt-4o"
    settings["contextual_rag_llm_provider"] = "openai"
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    updated["contextual_rag_llm_provider"] = "azure"
    _update_inference_settings(admin_user, updated)

    final = _get_current_search_settings(admin_user)
    assert final["contextual_rag_llm_name"] == "gpt-4o"
    assert final["contextual_rag_llm_provider"] == "azure"


def test_enable_contextual_rag_preserved_on_inference_update(
    admin_user: DATestUser,
) -> None:
    """Verify that enable_contextual_rag cannot be toggled via update-inference-settings
    because it is a preserved field."""
    settings = _get_current_search_settings(admin_user)
    original_enable = settings["enable_contextual_rag"]

    # Attempt to flip the flag
    settings["enable_contextual_rag"] = not original_enable
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["enable_contextual_rag"] == original_enable


def test_model_name_preserved_on_inference_update(
    admin_user: DATestUser,
) -> None:
    """Verify that model_name cannot be changed via update-inference-settings
    because it is a preserved field."""
    settings = _get_current_search_settings(admin_user)
    original_model_name = settings["model_name"]

    settings["model_name"] = "some-other-model"
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["model_name"] == original_model_name


def test_contextual_rag_settings_reflected_in_get_all(
    admin_user: DATestUser,
) -> None:
    """Verify that contextual RAG updates appear in get-all-search-settings."""
    settings = _get_current_search_settings(admin_user)
    settings["contextual_rag_llm_name"] = "test-model"
    settings["contextual_rag_llm_provider"] = "test-provider"
    _update_inference_settings(admin_user, settings)

    all_settings = _get_all_search_settings(admin_user)
    current = all_settings["current_settings"]
    assert current["contextual_rag_llm_name"] == "test-model"
    assert current["contextual_rag_llm_provider"] == "test-provider"
