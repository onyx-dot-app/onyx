"""
Integration tests for Auto LLM model update feature.

These tests verify that LLM providers with auto-update on get the models
their lab releases via the celery background task.

Environment variables for testing:
- AUTO_LLM_UPDATE_INTERVAL_SECONDS: Set to a low value (e.g., 5) for faster tests

The celery beat scheduler will run the check_for_auto_llm_updates task
at the configured interval.
"""

import time

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


def _create_provider_with_api(
    admin_user: DATestUser,
    name: str,
    provider_type: str,
    default_model: str,
    is_auto_mode: bool,
    model_configurations: list[dict] | None = None,
) -> dict:
    """Create an LLM provider via the API."""
    if model_configurations is None:
        model_configurations = [{"name": default_model, "is_visible": True}]

    llm_provider_data = {
        "name": name,
        "provider": provider_type,
        "api_key": "test-api-key-for-auto-mode-testing",
        "api_base": None,
        "api_version": None,
        "custom_config": None,
        "is_public": True,
        "is_auto_mode": is_auto_mode,
        "groups": [],
        "personas": [],
        "model_configurations": model_configurations,
        "api_key_changed": True,
    }

    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        json=llm_provider_data,
        headers=admin_user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_provider_by_id(admin_user: DATestUser, provider_id: int) -> dict:
    """Get a provider by ID via the API."""
    response = client.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    response.raise_for_status()
    for provider in response.json()["providers"]:
        if provider["id"] == provider_id:
            return provider
    raise ValueError(f"Provider with id {provider_id} not found")


def _get_catalog_model_names(admin_user: DATestUser, provider_name: str) -> list[str]:
    response = client.get(
        f"{API_SERVER_URL}/admin/llm/built-in/options/{provider_name}",
        headers=admin_user.headers,
    )
    response.raise_for_status()
    return [m["name"] for m in response.json()["known_models"]]


def _wait_for_catalog_baseline(provider_id: int, timeout_seconds: float = 90) -> None:
    """The first sync records the provider's catalog baseline."""
    from onyx.key_value_store.factory import get_kv_store
    from onyx.key_value_store.interface import KvKeyNotFoundError

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            get_kv_store().load(
                f"llm_auto_update_seen_models_{provider_id}", refresh_cache=True
            )
            return
        except KvKeyNotFoundError:
            time.sleep(2)
    raise AssertionError("The auto-update sync did not run for the provider")


def test_auto_update_keeps_the_admin_selection(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """The background sync does not reselect deselected models, add the
    catalog models the admin left out at setup, or remove custom models."""
    catalog = _get_catalog_model_names(admin_user, "openai")
    assert len(catalog) >= 2
    model_configurations = [
        {"name": catalog[0], "is_visible": True},
        {"name": catalog[1], "is_visible": False},
        {"name": "my-custom-finetuned-model", "is_visible": True},
    ]

    provider = _create_provider_with_api(
        admin_user=admin_user,
        name="test-auto-sync-openai",
        provider_type="openai",
        default_model=catalog[0],
        is_auto_mode=True,
        model_configurations=model_configurations,
    )
    assert provider["is_auto_mode"] is True

    _wait_for_catalog_baseline(provider["id"])

    synced_provider = _get_provider_by_id(admin_user, provider["id"])
    visibility = {
        m["name"]: m["is_visible"] for m in synced_provider["model_configurations"]
    }
    assert visibility == {m["name"]: m["is_visible"] for m in model_configurations}


def test_aggregator_provider_does_not_get_auto_update(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    provider = _create_provider_with_api(
        admin_user=admin_user,
        name="test-auto-sync-openrouter",
        provider_type="openrouter",
        default_model="z-ai/glm-5.3",
        is_auto_mode=True,
    )
    assert provider["is_auto_mode"] is False


def test_manual_mode_provider_not_affected_by_auto_sync(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """
    Test that a provider in Manual mode is NOT affected by auto sync.

    This test:
    1. Creates an OpenAI provider in Manual mode with custom models
    2. Waits for a period longer than the sync interval
    3. Verifies the models remain unchanged
    """
    custom_model = "my-custom-finetuned-model"

    # Create a provider in Manual mode
    provider = _create_provider_with_api(
        admin_user=admin_user,
        name="test-manual-mode-unchanged",
        provider_type="openai",
        default_model=custom_model,
        is_auto_mode=False,  # Manual mode
        model_configurations=[
            {"name": custom_model, "is_visible": True},
            {"name": "another-custom-model", "is_visible": True},
        ],
    )

    assert provider["is_auto_mode"] is False
    initial_models = {m["name"] for m in provider["model_configurations"]}
    print(f"Created manual mode provider with models: {initial_models}")

    # Wait for longer than the sync interval
    wait_time = 15  # Should be longer than AUTO_LLM_UPDATE_INTERVAL_SECONDS
    print(f"Waiting {wait_time}s to ensure sync task runs...")
    time.sleep(wait_time)

    # Verify models are unchanged
    updated_provider = _get_provider_by_id(admin_user, provider["id"])
    current_models = {m["name"] for m in updated_provider["model_configurations"]}

    assert current_models == initial_models, (
        f"Manual mode provider models should not change. Initial: {initial_models}, Current: {current_models}"
    )
