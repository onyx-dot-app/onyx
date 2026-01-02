import os
from uuid import uuid4

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestImageGenerationConfig
from tests.integration.common_utils.test_models import DATestUser


class ImageGenerationConfigManager:
    @staticmethod
    def create(
        image_provider_id: str | None = None,
        model_name: str = "gpt-image-1",
        provider: str = "openai",
        api_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        is_default: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> DATestImageGenerationConfig:
        """Create a new image generation config with new credentials."""
        image_provider_id = image_provider_id or f"test-provider-{uuid4()}"

        response = requests.post(
            f"{API_SERVER_URL}/admin/image-generation/config",
            json={
                "image_provider_id": image_provider_id,
                "model_name": model_name,
                "provider": provider,
                "api_key": api_key or os.environ["OPENAI_API_KEY"],
                "api_base": api_base,
                "api_version": api_version,
                "deployment_name": deployment_name,
                "is_default": is_default,
            },
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        data = response.json()

        return DATestImageGenerationConfig(
            image_provider_id=data["image_provider_id"],
            model_configuration_id=data["model_configuration_id"],
            model_name=data["model_name"],
            llm_provider_id=data["llm_provider_id"],
            llm_provider_name=data["llm_provider_name"],
            is_default=data["is_default"],
        )

    @staticmethod
    def create_from_provider(
        source_llm_provider_id: int,
        image_provider_id: str | None = None,
        model_name: str = "gpt-image-1",
        api_base: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        is_default: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> DATestImageGenerationConfig:
        """Create a new image generation config by cloning from an existing LLM provider."""
        image_provider_id = image_provider_id or f"test-provider-{uuid4()}"

        response = requests.post(
            f"{API_SERVER_URL}/admin/image-generation/config",
            json={
                "image_provider_id": image_provider_id,
                "model_name": model_name,
                "source_llm_provider_id": source_llm_provider_id,
                "api_base": api_base,
                "api_version": api_version,
                "deployment_name": deployment_name,
                "is_default": is_default,
            },
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        data = response.json()

        return DATestImageGenerationConfig(
            image_provider_id=data["image_provider_id"],
            model_configuration_id=data["model_configuration_id"],
            model_name=data["model_name"],
            llm_provider_id=data["llm_provider_id"],
            llm_provider_name=data["llm_provider_name"],
            is_default=data["is_default"],
        )

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestImageGenerationConfig]:
        """Get all image generation configs."""
        response = requests.get(
            f"{API_SERVER_URL}/admin/image-generation/config",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [DATestImageGenerationConfig(**config) for config in response.json()]

    @staticmethod
    def get_credentials(
        image_provider_id: str,
        user_performing_action: DATestUser | None = None,
    ) -> dict:
        """Get credentials for an image generation config."""
        response = requests.get(
            f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}/credentials",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def update(
        image_provider_id: str,
        model_name: str,
        provider: str | None = None,
        api_key: str | None = None,
        source_llm_provider_id: int | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestImageGenerationConfig:
        """Update an existing image generation config."""
        payload: dict = {
            "model_name": model_name,
            "api_base": api_base,
            "api_version": api_version,
            "deployment_name": deployment_name,
        }

        if source_llm_provider_id is not None:
            payload["source_llm_provider_id"] = source_llm_provider_id
        elif api_key is not None and provider is not None:
            payload["provider"] = provider
            payload["api_key"] = api_key
        else:
            raise ValueError(
                f"Either source_llm_provider_id or (api_key + provider) must be provided. "
                f"Got: source_llm_provider_id={source_llm_provider_id}, provider={provider}, api_key={'***' if api_key else None}"
            )

        headers = {**GENERAL_HEADERS}
        if user_performing_action:
            headers.update(user_performing_action.headers)

        response = requests.put(
            f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}",
            json=payload,
            headers=headers,
        )
        if not response.ok:
            print(f"Update failed with status {response.status_code}: {response.text}")
        response.raise_for_status()
        data = response.json()

        return DATestImageGenerationConfig(
            image_provider_id=data["image_provider_id"],
            model_configuration_id=data["model_configuration_id"],
            model_name=data["model_name"],
            llm_provider_id=data["llm_provider_id"],
            llm_provider_name=data["llm_provider_name"],
            is_default=data["is_default"],
        )

    @staticmethod
    def delete(
        image_provider_id: str,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        """Delete an image generation config."""
        response = requests.delete(
            f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def set_default(
        image_provider_id: str,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        """Set an image generation config as the default."""
        response = requests.post(
            f"{API_SERVER_URL}/admin/image-generation/config/{image_provider_id}/default",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def verify(
        config: DATestImageGenerationConfig,
        verify_deleted: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        """Verify that a config exists (or doesn't exist if verify_deleted=True)."""
        all_configs = ImageGenerationConfigManager.get_all(user_performing_action)

        for fetched_config in all_configs:
            if fetched_config.image_provider_id == config.image_provider_id:
                if verify_deleted:
                    raise ValueError(
                        f"ImageGenerationConfig {config.image_provider_id} found but should be deleted"
                    )
                # Verify the config matches
                if (
                    fetched_config.model_name == config.model_name
                    and fetched_config.is_default == config.is_default
                ):
                    return

        if not verify_deleted:
            raise ValueError(
                f"ImageGenerationConfig {config.image_provider_id} not found"
            )
