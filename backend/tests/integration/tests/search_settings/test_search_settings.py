import httpx

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser

SEARCH_SETTINGS_URL = f"{API_SERVER_URL}/search-settings"


def _get_current_search_settings(user: DATestUser) -> dict:
    response = client.get(
        f"{SEARCH_SETTINGS_URL}/get-current-search-settings",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_all_search_settings(user: DATestUser) -> dict:
    response = client.get(
        f"{SEARCH_SETTINGS_URL}/get-all-search-settings",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_secondary_search_settings(user: DATestUser) -> dict | None:
    response = client.get(
        f"{SEARCH_SETTINGS_URL}/get-secondary-search-settings",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _set_new_search_settings(
    user: DATestUser,
    current_settings: dict,
    enable_contextual_rag: bool = False,
    contextual_rag_model_configuration_id: int | None = None,
) -> httpx.Response:
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
        "contextual_rag_model_configuration_id": contextual_rag_model_configuration_id,
    }
    return client.post(
        f"{SEARCH_SETTINGS_URL}/set-new-search-settings",
        json=payload,
        headers=user.headers,
    )


def _cancel_new_embedding(user: DATestUser) -> None:
    response = client.post(
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
    assert "contextual_rag_model_configuration_id" in settings
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


def test_contextual_rag_model_update_requires_enabled_feature(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    mc_id = llm_provider.model_configuration_ids[0]
    settings = _get_current_search_settings(admin_user)
    settings["enable_contextual_rag"] = True
    settings["contextual_rag_model_configuration_id"] = mc_id
    response = client.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert "must be enabled" in response.json()["detail"]
    assert (
        _get_current_search_settings(admin_user)[
            "contextual_rag_model_configuration_id"
        ]
        is None
    )


def test_disabled_contextual_rag_rejected_before_embedding_model_change(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    settings = _get_current_search_settings(admin_user)
    settings["model_name"] = "some-other-model"
    settings["contextual_rag_model_configuration_id"] = (
        llm_provider.model_configuration_ids[0]
    )
    response = client.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=settings,
        headers=admin_user.headers,
    )
    assert response.status_code == 400
    assert "must be enabled" in response.json()["detail"]


def test_set_new_search_settings_with_contextual_rag(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Create new search settings with contextual RAG enabled and verify the
    secondary settings contain the correct model configuration ID."""
    mc_id = llm_provider.model_configuration_ids[0]
    current = _get_current_search_settings(admin_user)

    response = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=True,
        contextual_rag_model_configuration_id=mc_id,
    )
    response.raise_for_status()
    assert "id" in response.json()

    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is not None
    assert secondary["enable_contextual_rag"] is True
    assert secondary["contextual_rag_model_configuration_id"] == mc_id

    _cancel_new_embedding(admin_user)


def test_set_new_search_settings_without_contextual_rag(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Create new search settings with contextual RAG disabled and verify
    the secondary settings have no RAG model configuration."""
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
    assert secondary["contextual_rag_model_configuration_id"] is None

    _cancel_new_embedding(admin_user)


def test_inference_update_rejects_active_reindex(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    mc_id = llm_provider.model_configuration_ids[0]
    current = _get_current_search_settings(admin_user)

    response = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=False,
    )
    response.raise_for_status()

    current["enable_contextual_rag"] = True
    current["contextual_rag_model_configuration_id"] = mc_id
    update_response = client.post(
        f"{SEARCH_SETTINGS_URL}/update-inference-settings",
        json=current,
        headers=admin_user.headers,
    )
    assert update_response.status_code == 409

    all_settings = _get_all_search_settings(admin_user)
    primary = all_settings["current_settings"]
    assert primary["contextual_rag_model_configuration_id"] is None
    secondary = all_settings["secondary_settings"]
    assert secondary is not None
    assert secondary["contextual_rag_model_configuration_id"] is None

    _cancel_new_embedding(admin_user)


def test_new_reindex_refused_while_one_in_progress(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """Only one re-index at a time: starting a second while the first is in progress is
    refused (409), and the first is left untouched (not superseded). To change it, cancel
    the in-progress re-index and start a new one."""
    mc_id = llm_provider.model_configuration_ids[0]
    current = _get_current_search_settings(admin_user)

    resp1 = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=False,
    )
    resp1.raise_for_status()

    resp2 = _set_new_search_settings(
        user=admin_user,
        current_settings=current,
        enable_contextual_rag=True,
        contextual_rag_model_configuration_id=mc_id,
    )
    assert resp2.status_code == 409

    # The in-progress re-index is untouched — still the first one (RAG off).
    secondary = _get_secondary_search_settings(admin_user)
    assert secondary is not None
    assert secondary["enable_contextual_rag"] is False

    _cancel_new_embedding(admin_user)
