from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class AzureImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        api_key: str,
        api_base: str,
        api_version: str,
        deployment_name: str | None = None,
    ):
        self._api_key = api_key
        self._api_base = api_base
        self._api_version = api_version
        self._deployment_name = deployment_name

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        return all(
            [
                credentials.api_key,
                credentials.api_base,
                credentials.api_version,
            ]
        )

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> AzureImageGenerationProvider:
        assert credentials.api_key
        assert credentials.api_base
        assert credentials.api_version

        return cls(
            api_key=credentials.api_key,
            api_base=credentials.api_base,
            api_version=credentials.api_version,
            deployment_name=credentials.deployment_name,
        )

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResponse:
        from litellm import image_generation

        deployment = self._deployment_name or model
        model_name = f"azure/{deployment}"

        return image_generation(
            prompt=prompt,
            model=model_name,
            api_key=self._api_key,
            api_base=self._api_base,
            api_version=self._api_version,
            size=size,
            n=n,
            quality=quality,
            **kwargs,
        )
