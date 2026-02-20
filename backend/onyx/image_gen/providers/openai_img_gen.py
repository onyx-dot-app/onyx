from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class OpenAIImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
    ):
        self._api_key = api_key
        self._api_base = api_base

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        return bool(credentials.api_key)

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> OpenAIImageGenerationProvider:
        assert credentials.api_key

        return cls(
            api_key=credentials.api_key,
            api_base=credentials.api_base,
        )

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        reference_images: list[ReferenceImage] | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> ImageGenerationResponse:
        from litellm import image_generation

        return image_generation(
            prompt=prompt,
            model=model,
            api_key=self._api_key,
            api_base=self._api_base,
            size=size,
            n=n,
            quality=quality,
            **kwargs,
        )
