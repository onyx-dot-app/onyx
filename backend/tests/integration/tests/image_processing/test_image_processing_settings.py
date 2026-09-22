from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.image_processing import (
    ImageProcessingManager,
)
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser


def test_image_processing_round_trip(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Off by default; PUT turns it on; a second PUT repoints; DELETE turns it off."""
    assert ImageProcessingManager.get(admin_user) is None

    first = LLMProviderManager.create(
        name="vision-a", default_model_name="gpt-4o", user_performing_action=admin_user
    )
    second = LLMProviderManager.create(
        name="vision-b",
        default_model_name="gpt-4o-mini",
        set_as_default=False,
        user_performing_action=admin_user,
    )
    first_model_id = first.model_configuration_ids[0]
    second_model_id = second.model_configuration_ids[0]

    created = ImageProcessingManager.enable(admin_user, first_model_id)
    assert created == {"model_configuration_id": first_model_id, "max_size_mb": 20}
    assert ImageProcessingManager.get(admin_user) == created

    repointed = ImageProcessingManager.enable(
        admin_user, second_model_id, max_size_mb=5
    )
    assert repointed == {"model_configuration_id": second_model_id, "max_size_mb": 5}
    assert ImageProcessingManager.get(admin_user) == repointed

    ImageProcessingManager.disable(admin_user)
    assert ImageProcessingManager.get(admin_user) is None

    # Disabling twice is a no-op, not an error.
    ImageProcessingManager.disable(admin_user)
    assert ImageProcessingManager.get(admin_user) is None


def test_image_processing_rejects_models_without_vision(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json={
            "name": "text-only",
            "provider": "openai",
            "api_key": "sk-000000000000000000000000000000000000000000000001",
            "model_configurations": [
                # A current model: the provider response drops obsolete
                # names such as gpt-3.5, which would hide the id read below.
                {
                    "name": "o3-mini",
                    "is_visible": True,
                    "supports_image_input": False,
                }
            ],
            "is_public": True,
            "groups": [],
        },
    )
    assert response.status_code == 200
    text_only_model_id = response.json()["model_configurations"][0]["id"]

    rejected = client.put(
        f"{API_SERVER_URL}/admin/image-processing",
        json={"model_configuration_id": text_only_model_id},
        headers=admin_user.headers,
    )
    assert rejected.status_code == 400
    assert ImageProcessingManager.get(admin_user) is None

    missing = client.put(
        f"{API_SERVER_URL}/admin/image-processing",
        json={"model_configuration_id": 999_999},
        headers=admin_user.headers,
    )
    assert missing.status_code == 400


def test_deleting_the_provider_turns_image_processing_off(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """The FK cascades: no dangling pointer, the feature is simply off."""
    LLMProviderManager.create(name="chat-default", user_performing_action=admin_user)
    vision = LLMProviderManager.create(
        name="vision-only",
        default_model_name="gpt-4o",
        set_as_default=False,
        user_performing_action=admin_user,
    )
    ImageProcessingManager.enable(admin_user, vision.model_configuration_ids[0])
    assert ImageProcessingManager.get(admin_user) is not None

    LLMProviderManager.delete(vision, user_performing_action=admin_user)

    assert ImageProcessingManager.get(admin_user) is None


def test_hiding_the_image_processing_model_is_refused(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """A model the captioner points at cannot be hidden by a provider edit."""
    provider = LLMProviderManager.create(
        name="vision-edit",
        default_model_name="gpt-4o",
        user_performing_action=admin_user,
    )
    ImageProcessingManager.enable(admin_user, provider.model_configuration_ids[0])

    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "id": provider.id,
            "name": provider.name,
            "provider": provider.provider,
            "api_key": provider.api_key,
            "api_key_changed": True,
            "model_configurations": [
                {"name": "gpt-4o", "is_visible": False, "supports_image_input": True}
            ],
            "is_public": True,
            "groups": [],
        },
    )
    assert response.status_code == 400
    assert "image_processing" in response.json()["detail"]
