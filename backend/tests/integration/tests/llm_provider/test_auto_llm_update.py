"""
Integration tests for Auto LLM model update feature.

These tests verify that LLM providers in Auto mode get their models
automatically synced from the GitHub config via the celery background task.

Environment variables for testing:
- AUTO_LLM_UPDATE_INTERVAL_SECONDS: Set to a low value (e.g., 5) for faster tests
- AUTO_LLM_CONFIG_URL: Points to the config file to sync from

The celery beat scheduler will run the check_for_auto_llm_updates task
at the configured interval.
"""

import time

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser

# Skip all tests in this module
pytestmark = pytest.mark.skip(reason="Auto LLM update tests temporarily disabled")


# How long to wait for the celery task to run and sync models
# This should be longer than AUTO_LLM_UPDATE_INTERVAL_SECONDS
MAX_WAIT_TIME_SECONDS = 60
POLL_INTERVAL_SECONDS = 5


@pytest.fixture(scope="module", autouse=True)
def reset_for_module() -> None:
    """Reset all data once before running any tests in this module."""
    reset_all()


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
        "default_model_name": default_model,
        "api_key": "test-api-key-for-auto-mode-testing",
        "api_base": None,
        "api_version": None,
        "custom_config": None,
        "fast_default_model_name": default_model,
        "is_public": True,
        "is_auto_mode": is_auto_mode,
        "groups": [],
        "personas": [],
        "model_configurations": model_configurations,
        "api_key_changed": True,
    }

    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        json=llm_provider_data,
        headers=admin_user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_provider_by_id(admin_user: DATestUser, provider_id: int) -> dict:
    """Get a provider by ID via the API."""
    response = requests.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    response.raise_for_status()
    for provider in response.json():
        if provider["id"] == provider_id:
            return provider
    raise ValueError(f"Provider with id {provider_id} not found")


def get_auto_config(admin_user: DATestUser) -> dict | None:
    """Get the current auto config from the API."""
    response = requests.get(
        f"{API_SERVER_URL}/admin/llm/auto-config",
        headers=admin_user.headers,
    )
    if response.status_code == 502:
        return None
    response.raise_for_status()
    return response.json()


def wait_for_model_sync(
    admin_user: DATestUser,
    provider_id: int,
    expected_model_names: set[str],
    max_wait_seconds: int = MAX_WAIT_TIME_SECONDS,
) -> dict:
    """
    Wait for the provider's models to match the expected set.

    Returns the provider data once models match, or raises an assertion error.
    """
    start_time = time.time()
    last_provider: dict | None = None

    while time.time() - start_time < max_wait_seconds:
        provider = _get_provider_by_id(admin_user, provider_id)
        last_provider = provider
        current_models = {m["name"] for m in provider["model_configurations"]}

        # Check if we have all expected models
        if expected_model_names.issubset(current_models):
            return provider

        print(
            f"Waiting for model sync... "
            f"Current: {current_models}, Expected: {expected_model_names}"
        )
        time.sleep(POLL_INTERVAL_SECONDS)

    # Timeout - return last state for debugging
    current_models = (
        {m["name"] for m in last_provider["model_configurations"]}
        if last_provider
        else set()
    )
    raise AssertionError(
        f"Model sync timed out after {max_wait_seconds}s. "
        f"Current models: {current_models}, Expected: {expected_model_names}"
    )


def test_auto_mode_provider_gets_synced_from_github_config(
    admin_user: DATestUser,
) -> None:
    """
    Test that a provider in Auto mode gets its models synced from GitHub config.

    This test:
    1. Fetches the current GitHub config to know what models to expect
    2. Creates an OpenAI provider in Auto mode with outdated/minimal models
    3. Waits for the celery task to sync models from GitHub
    4. Verifies the models match the GitHub config
    """
    # First, get the GitHub config to know what models we should expect
    github_config = get_auto_config(admin_user)
    if github_config is None:
        pytest.skip("GitHub config not found")

    # Get expected models for OpenAI from the config
    if "openai" not in github_config.get("providers", {}):
        pytest.fail("OpenAI not in GitHub config")

    openai_config = github_config["providers"]["openai"]

    # Build expected model names from default_model + additional_visible_models
    expected_models: set[str] = set()

    # Add default model
    default_model = openai_config.get("default_model", {})
    if isinstance(default_model, dict):
        expected_models.add(default_model["name"])
    elif isinstance(default_model, str):
        expected_models.add(default_model)

    # Add additional visible models
    for model in openai_config.get("additional_visible_models", []):
        if isinstance(model, dict):
            expected_models.add(model["name"])
        elif isinstance(model, str):
            expected_models.add(model)

    print(f"Expected models from GitHub config: {expected_models}")

    # Create an OpenAI provider in Auto mode with a single outdated model
    provider = _create_provider_with_api(
        admin_user=admin_user,
        name="test-auto-sync-openai",
        provider_type="openai",
        default_model="outdated-model-name",
        is_auto_mode=True,
        model_configurations=[
            {"name": "outdated-model-name", "is_visible": True},
        ],
    )

    assert provider["is_auto_mode"] is True
    print(f"Created provider {provider['id']} in Auto mode")

    # Wait for the celery task to sync models
    # The task runs at AUTO_LLM_UPDATE_INTERVAL_SECONDS interval
    synced_provider = wait_for_model_sync(
        admin_user=admin_user,
        provider_id=provider["id"],
        expected_model_names=expected_models,
    )

    # Verify the models were synced
    synced_model_names = {m["name"] for m in synced_provider["model_configurations"]}
    print(f"Synced models: {synced_model_names}")

    assert expected_models.issubset(
        synced_model_names
    ), f"Expected models {expected_models} not found in synced models {synced_model_names}"

    # Verify the outdated model was removed
    assert (
        "outdated-model-name" not in synced_model_names
    ), "Outdated model should have been removed by sync"

    # Verify default model was set from GitHub config
    expected_default = (
        default_model["name"] if isinstance(default_model, dict) else default_model
    )
    assert synced_provider["default_model_name"] == expected_default, (
        f"Default model should be {expected_default}, "
        f"got {synced_provider['default_model_name']}"
    )


def test_manual_mode_provider_not_affected_by_auto_sync(
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
        f"Manual mode provider models should not change. "
        f"Initial: {initial_models}, Current: {current_models}"
    )

    assert (
        updated_provider["default_model_name"] == custom_model
    ), f"Manual mode default model should remain {custom_model}"
