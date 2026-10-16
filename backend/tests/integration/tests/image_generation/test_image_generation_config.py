"""Integration tests for image generation config endpoints.

Tests cover CRUD operations for /admin/image-generation/config endpoints.
The /admin/image-generation/test endpoint is not tested as it makes real API calls.

Uses module-scoped fixtures to reset DB and create users once per module for faster execution.
"""

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.image_generation import (
    ImageGenerationConfigManager,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module")
def setup_image_generation_tests() -> DATestUser:
    """Module-scoped fixture that runs once for all tests in this module.

    - Resets DB once at the start of the module
    - Creates admin user once, for all tests to use
    """
    reset_all()
    return UserManager.create(name="admin_user")


def test_create_image_generation_config(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test creating an image generation config with new credentials."""
    admin_user = setup_image_generation_tests

    config = ImageGenerationConfigManager.create(
        image_provider_id="test-openai-dalle",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-test-key-12345",
        is_default=False,
        user_performing_action=admin_user,
    )

    assert config.image_provider_id == "test-openai-dalle"
    assert config.model_name == "gpt-image-1"
    assert config.is_default is False

    # Verify it exists in the list
    ImageGenerationConfigManager.verify(
        config=config,
        user_performing_action=admin_user,
    )


def test_create_duplicate_config_fails(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test that creating a config with an existing image_provider_id fails."""
    admin_user = setup_image_generation_tests

    # Create first config
    ImageGenerationConfigManager.create(
        image_provider_id="duplicate-test-id",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-test-key-1",
        user_performing_action=admin_user,
    )

    # Try to create another with the same image_provider_id
    response = client.post(
        f"{API_SERVER_URL}/admin/image-generation/config",
        json={
            "image_provider_id": "duplicate-test-id",
            "model_name": "gpt-image-1",
            "provider": "openai",
            "api_key": "sk-test-key-2",
        },
        headers=admin_user.headers,
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_get_all_configs(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test getting all image generation configs."""
    admin_user = setup_image_generation_tests

    # Create multiple configs
    config1 = ImageGenerationConfigManager.create(
        image_provider_id="config-1",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-key-1",
        user_performing_action=admin_user,
    )
    config2 = ImageGenerationConfigManager.create(
        image_provider_id="config-2",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-key-2",
        user_performing_action=admin_user,
    )

    # Get all configs
    all_configs = ImageGenerationConfigManager.get_all(
        user_performing_action=admin_user
    )

    assert len(all_configs) >= 2
    config_ids = [c.image_provider_id for c in all_configs]
    assert config1.image_provider_id in config_ids
    assert config2.image_provider_id in config_ids


def test_get_config_credentials(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test getting credentials for an image generation config."""
    admin_user = setup_image_generation_tests

    test_api_key = "sk-test-credentials-key-12345"
    config = ImageGenerationConfigManager.create(
        image_provider_id="credentials-test",
        model_name="gpt-image-1",
        provider="openai",
        api_key=test_api_key,
        user_performing_action=admin_user,
    )

    # Get credentials
    credentials = ImageGenerationConfigManager.get_credentials(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )

    # Credentials should contain the masked API key (first 4 + ... + last 4)
    assert credentials["api_key"] == "sk-t...2345"
    assert "api_base" in credentials
    assert "api_version" in credentials
    assert "deployment_name" in credentials


def test_get_credentials_not_found(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test getting credentials for a non-existent config returns 404."""
    admin_user = setup_image_generation_tests

    response = client.get(
        f"{API_SERVER_URL}/admin/image-generation/config/non-existent-id/credentials",
        headers=admin_user.headers,
    )

    assert response.status_code == 404


def test_update_config_direct_key_entry(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test updating an image generation config with new direct credentials."""
    admin_user = setup_image_generation_tests

    # Create initial config
    config = ImageGenerationConfigManager.create(
        image_provider_id="update-direct-test",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-initial-key",
        user_performing_action=admin_user,
    )

    assert config.model_name == "gpt-image-1"

    # Update with new credentials and model
    new_api_key = "sk-updated-key-12345"
    updated_config = ImageGenerationConfigManager.update(
        image_provider_id=config.image_provider_id,
        model_name="gpt-image-1",
        provider="openai",
        api_key=new_api_key,
        user_performing_action=admin_user,
    )

    assert updated_config.image_provider_id == config.image_provider_id
    assert updated_config.model_name == "gpt-image-1"

    # Verify credentials were updated (masked: first 4 + ... + last 4)
    credentials = ImageGenerationConfigManager.get_credentials(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )
    assert credentials["api_key"] == "sk-u...2345"


def test_update_config_keeps_saved_key(
    setup_image_generation_tests: DATestUser,
) -> None:
    """An update that sends the saved key as an existing token keeps that
    token, though the config gets a new hidden LLM provider."""
    admin_user = setup_image_generation_tests

    config = ImageGenerationConfigManager.create(
        image_provider_id="update-keep-key-test",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-kept-key-12345",
        user_performing_action=admin_user,
    )
    before = ImageGenerationConfigManager.get_credentials(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )
    assert before["api_token_id"] is not None

    response = client.put(
        f"{API_SERVER_URL}/admin/image-generation/config/{config.image_provider_id}",
        json={
            "model_name": "gpt-image-1",
            "provider": "openai",
            "api_key": {"type": "existing", "id": before["api_token_id"]},
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    assert response.json()["llm_provider_id"] != config.llm_provider_id

    after = ImageGenerationConfigManager.get_credentials(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )
    assert after["api_token_id"] == before["api_token_id"]
    assert after["api_key"] == "sk-k...2345"


def test_delete_config(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test deleting an image generation config."""
    admin_user = setup_image_generation_tests

    # Create a config
    config = ImageGenerationConfigManager.create(
        image_provider_id="delete-test",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-delete-key",
        user_performing_action=admin_user,
    )

    # Verify it exists
    ImageGenerationConfigManager.verify(
        config=config,
        user_performing_action=admin_user,
    )

    # Delete it
    ImageGenerationConfigManager.delete(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )

    # Verify it's deleted
    ImageGenerationConfigManager.verify(
        config=config,
        verify_deleted=True,
        user_performing_action=admin_user,
    )


def test_delete_config_not_found(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test deleting a non-existent config returns 404."""
    admin_user = setup_image_generation_tests

    response = client.delete(
        f"{API_SERVER_URL}/admin/image-generation/config/non-existent-id",
        headers=admin_user.headers,
    )

    assert response.status_code == 404


def test_set_default_config(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test setting a config as the default."""
    admin_user = setup_image_generation_tests

    # Create a config that is not default
    config = ImageGenerationConfigManager.create(
        image_provider_id="default-test",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-test-key",
        is_default=False,
        user_performing_action=admin_user,
    )

    assert config.is_default is False

    # Set it as default
    ImageGenerationConfigManager.set_default(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )

    # Verify it's now default
    all_configs = ImageGenerationConfigManager.get_all(
        user_performing_action=admin_user
    )
    updated_config = next(
        c for c in all_configs if c.image_provider_id == config.image_provider_id
    )
    assert updated_config.is_default is True


def test_set_default_clears_previous(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test that setting a new default clears the previous default."""
    admin_user = setup_image_generation_tests

    # Create first config as default
    config1 = ImageGenerationConfigManager.create(
        image_provider_id="first-default",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-key-1",
        is_default=True,
        user_performing_action=admin_user,
    )

    # Create second config not as default
    config2 = ImageGenerationConfigManager.create(
        image_provider_id="second-default",
        model_name="gpt-image-1",
        provider="openai",
        api_key="sk-key-2",
        is_default=False,
        user_performing_action=admin_user,
    )

    # Verify first is default
    all_configs = ImageGenerationConfigManager.get_all(
        user_performing_action=admin_user
    )
    first = next(
        c for c in all_configs if c.image_provider_id == config1.image_provider_id
    )
    second = next(
        c for c in all_configs if c.image_provider_id == config2.image_provider_id
    )
    assert first.is_default is True
    assert second.is_default is False

    # Set second as default
    ImageGenerationConfigManager.set_default(
        image_provider_id=config2.image_provider_id,
        user_performing_action=admin_user,
    )

    # Verify second is now default and first is not
    all_configs = ImageGenerationConfigManager.get_all(
        user_performing_action=admin_user
    )
    first = next(
        c for c in all_configs if c.image_provider_id == config1.image_provider_id
    )
    second = next(
        c for c in all_configs if c.image_provider_id == config2.image_provider_id
    )
    assert first.is_default is False
    assert second.is_default is True


def test_set_default_not_found(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test setting a non-existent config as default returns 404."""
    admin_user = setup_image_generation_tests

    response = client.post(
        f"{API_SERVER_URL}/admin/image-generation/config/non-existent-id/default",
        headers=admin_user.headers,
    )

    assert response.status_code == 404


def test_create_config_missing_credentials(
    setup_image_generation_tests: DATestUser,
) -> None:
    """Test that creating a config without credentials fails."""
    admin_user = setup_image_generation_tests

    # Try to create without api_key/provider
    response = client.post(
        f"{API_SERVER_URL}/admin/image-generation/config",
        json={
            "image_provider_id": "no-creds-test",
            "model_name": "gpt-image-1",
        },
        headers=admin_user.headers,
    )

    assert response.status_code == 400
    assert "No provider provided" in response.json()["detail"]
