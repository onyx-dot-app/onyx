import pytest
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


def _set_new_search_settings(
    user: DATestUser,
    current_settings: dict,
    enable_contextual_rag: bool = False,
    contextual_rag_llm_name: str | None = None,
    contextual_rag_llm_provider: str | None = None,
) -> requests.Response:
    """POST to set-new-search-settings, deriving the payload from current settings."""
    payload = {
        "model_name": current_settings["model_name"],
        "model_dim": current_settings["model_dim"],
        "normalize": current_settings["normalize"],
        "query_prefix": current_settings.get("query_prefix") or "",
        "passage_prefix": current_settings.get("passage_prefix") or "",
        "provider_type": current_settings.get("provider_type"),
        "index_name": None,
        "multipass_indexing": current_settings.get("multipass_indexing", False),
        "embedding_precision": current_settings["embedding_precision"],
        "reduced_dimension": current_settings.get("reduced_dimension"),
        "enable_contextual_rag": enable_contextual_rag,
        "contextual_rag_llm_name": contextual_rag_llm_name,
        "contextual_rag_llm_provider": contextual_rag_llm_provider,
    }
    return requests.post(
        f"{SEARCH_SETTINGS_URL}/set-new-search-settings",
        json=payload,
        headers=user.headers,
    )


def _cancel_new_embedding(user: DATestUser) -> None:
    response = requests.post(
        f"{SEARCH_SETTINGS_URL}/cancel-new-embedding",
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


@pytest.mark.skip(reason="Set new search settings is temporarily disabled.")
def test_set_new_search_settings_with_contextual_rag(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Create new search settings with contextual RAG enabled and verify the
    secondary settings contain the correct provider and model."""
    current = _get_current_search_settings(admin_user)

    response = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=True,
        contextual_rag_llm_name=llm_provider.default_model_name,
        contextual_rag_llm_provider=llm_provider.name,
    )
    response.raise_for_status()
    assert "id" in response.json()

    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is not None
    assert secondary["enable_contextual_rag"] is True
    assert secondary["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert secondary["contextual_rag_llm_provider"] == llm_provider.name

    _cancel_new_embedding(admin_user)


@pytest.mark.skip(reason="Set new search settings is temporarily disabled.")
def test_set_new_search_settings_without_contextual_rag(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Create new search settings with contextual RAG disabled and verify
    the secondary settings have no RAG provider."""
    current = _get_current_search_settings(admin_user)

    response = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=False,
    )
    response.raise_for_status()

    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is not None
    assert secondary["enable_contextual_rag"] is False
    assert secondary["contextual_rag_llm_name"] is None
    assert secondary["contextual_rag_llm_provider"] is None

    _cancel_new_embedding(admin_user)


@pytest.mark.skip(reason="Set new search settings is temporarily disabled.")
def test_set_new_then_update_inference_settings(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Create new secondary settings, then update the current (primary) settings
    with contextual RAG and verify both are visible through get-all."""
    current = _get_current_search_settings(admin_user)

    # Create secondary settings without contextual RAG
    response = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=False,
    )
    response.raise_for_status()

    # Update the *current* (primary) settings with a contextual RAG provider
    current["enable_contextual_rag"] = True
    current["contextual_rag_llm_name"] = llm_provider.default_model_name
    current["contextual_rag_llm_provider"] = llm_provider.name
    _update_inference_settings(admin_user, current)

    all_settings = _get_all_search_settings(admin_user)

    primary = all_settings["current_settings"]
    assert primary["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert primary["contextual_rag_llm_provider"] == llm_provider.name

    secondary = all_settings["secondary_settings"]
    assert secondary is not None
    assert secondary["contextual_rag_llm_name"] is None
    assert secondary["contextual_rag_llm_provider"] is None

    _cancel_new_embedding(admin_user)


@pytest.mark.skip(reason="Set new search settings is temporarily disabled.")
def test_set_new_search_settings_replaces_previous_secondary(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Calling set-new-search-settings twice should retire the first secondary
    and replace it with the second."""
    current = _get_current_search_settings(admin_user)

    # First: no contextual RAG
    resp1 = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=False,
    )
    resp1.raise_for_status()
    first_id = resp1.json()["id"]

    # Second: with contextual RAG
    resp2 = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=True,
        contextual_rag_llm_name=llm_provider.default_model_name,
        contextual_rag_llm_provider=llm_provider.name,
    )
    resp2.raise_for_status()
    second_id = resp2.json()["id"]

    assert second_id != first_id

    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is not None
    assert secondary["enable_contextual_rag"] is True
    assert secondary["contextual_rag_llm_name"] == llm_provider.default_model_name
    assert secondary["contextual_rag_llm_provider"] == llm_provider.name

    _cancel_new_embedding(admin_user)
