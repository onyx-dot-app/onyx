import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestLLMProvider
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


def test_get_current_search_settings(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Verify that GET current search settings returns expected fields."""
    settings = _get_current_search_settings(admin_user)

    assert "model_name" in settings
    assert "model_dim" in settings
    assert "enable_contextual_rag" in settings
    assert "contextual_rag_llm_name" in settings
    assert "contextual_rag_llm_provider" in settings
    assert "index_name" in settings
    assert "embedding_precision" in settings


def test_get_all_search_settings(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Verify that GET all search settings returns current and secondary."""
    all_settings = _get_all_search_settings(admin_user)

    assert "current_settings" in all_settings
    assert "secondary_settings" in all_settings
    assert all_settings["current_settings"] is not None
    assert "model_name" in all_settings["current_settings"]


def test_get_secondary_search_settings_none_by_default(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Verify that no secondary search settings exist by default."""
    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is None


def test_set_contextual_rag_model(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Set contextual RAG LLM model and verify it persists."""
    settings = _get_current_search_settings(admin_user)

    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = llm_provider.default_model_name
    settings["contextual_rag_llm_provider"] = llm_provider.name
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert updated["contextual_rag_llm_provider"] == llm_provider.name


def test_unset_contextual_rag_model(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Set a contextual RAG model, then unset it and verify it becomes None."""
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = llm_provider.default_model_name
    settings["contextual_rag_llm_provider"] = llm_provider.name
    _update_inference_settings(admin_user, settings)

    # Verify it's set
    updated = _get_current_search_settings(admin_user)
    assert updated["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert updated["contextual_rag_llm_provider"] == llm_provider.name

    # Unset by disabling contextual RAG
    updated["enable_contextual_rag"] = False
    updated["contextual_rag_llm_name"] = None
    updated["contextual_rag_llm_provider"] = None
    _update_inference_settings(admin_user, updated)

    # Verify it's unset
    final = _get_current_search_settings(admin_user)
    assert final["contextual_rag_llm_name"] is None
    assert final["contextual_rag_llm_provider"] is None


def test_change_contextual_rag_model(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Change contextual RAG from one model to another and verify the switch."""
    second_provider = LLMProviderManager.create(
        name="second-provider",
        default_model_name="gpt-4o",
        user_performing_action=admin_user,
    )

    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = llm_provider.default_model_name
    settings["contextual_rag_llm_provider"] = llm_provider.name
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert updated["contextual_rag_llm_provider"] == llm_provider.name

    # Switch to a different model and provider
    updated["enable_contextual_rag"] = True
    updated["contextual_rag_llm_name"] = second_provider.default_model_name
    updated["contextual_rag_llm_provider"] = second_provider.name
    _update_inference_settings(admin_user, updated)

    final = _get_current_search_settings(admin_user)
    assert final["contextual_rag_llm_name"] == second_provider.default_model_name
    assert final["contextual_rag_llm_provider"] == second_provider.name


def test_change_contextual_rag_provider_only(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Change only the provider while keeping the same model name."""
    shared_model_name = llm_provider.default_model_name
    second_provider = LLMProviderManager.create(
        name="second-provider",
        default_model_name=shared_model_name,
        user_performing_action=admin_user,
    )

    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = shared_model_name
    settings["contextual_rag_llm_provider"] = llm_provider.name
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    updated["enable_contextual_rag"] = True
    updated["contextual_rag_llm_provider"] = second_provider.name
    _update_inference_settings(admin_user, updated)

    final = _get_current_search_settings(admin_user)
    assert final["contextual_rag_llm_name"] == shared_model_name
    assert final["contextual_rag_llm_provider"] == second_provider.name


def test_enable_contextual_rag_preserved_on_inference_update(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Verify that enable_contextual_rag cannot be toggled via update-inference-settings
    because it is a preserved field."""
    settings = _get_current_search_settings(admin_user)
    original_enable = settings["enable_contextual_rag"]

    # Attempt to flip the flag
    settings["enable_contextual_rag"] = not original_enable
    settings["contextual_rag_llm_name"] = None
    settings["contextual_rag_llm_provider"] = None
    _update_inference_settings(admin_user, settings)

    updated = _get_current_search_settings(admin_user)
    assert updated["enable_contextual_rag"] == original_enable


def test_model_name_preserved_on_inference_update(
    reset: None,  # noqa: ARG001
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
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Verify that contextual RAG updates appear in get-all-search-settings."""
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = llm_provider.default_model_name
    settings["contextual_rag_llm_provider"] = llm_provider.name
    _update_inference_settings(admin_user, settings)

    all_settings = _get_all_search_settings(admin_user)
    current = all_settings["current_settings"]
    assert current["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert current["contextual_rag_llm_provider"] == llm_provider.name


def test_update_contextual_rag_nonexistent_provider(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Updating with a provider that does not exist should return 400."""
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = "some-model"
    settings["contextual_rag_llm_provider"] = "nonexistent-provider"

    response = requests.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert "Provider nonexistent-provider not found" in response.json()["detail"]


def test_update_contextual_rag_nonexistent_model(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Updating with a valid provider but a model not in that provider should return 400."""
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = "nonexistent-model"
    settings["contextual_rag_llm_provider"] = llm_provider.name

    response = requests.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert (
        f"Model nonexistent-model not found in provider {llm_provider.name}"
        in response.json()["detail"]
    )


def test_update_contextual_rag_missing_provider_name(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Providing a model name without a provider name should return 400."""
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = "some-model"
    settings["contextual_rag_llm_provider"] = None

    response = requests.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert "Provider name and model name are required" in response.json()["detail"]


def test_update_contextual_rag_missing_model_name(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Providing a provider name without a model name should return 400."""
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_llm_name"] = None
    settings["contextual_rag_llm_provider"] = llm_provider.name

    response = requests.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert "Provider name and model name are required" in response.json()["detail"]
