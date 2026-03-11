from __future__ import annotations

import abc
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel

from onyx.image_gen.exceptions import ImageProviderCredentialsError

if TYPE_CHECKING:
    from litellm.types.utils import ImageResponse as ImageGenerationResponse


class ImageGenerationProviderCredentials(BaseModel):
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
    custom_config: dict[str, str] | None = None


class ReferenceImage(BaseModel):
    data: bytes
    mime_type: str


class ImageGenerationProvider(abc.ABC):
    @property
    def supports_reference_images(self) -> bool:
        return False

    @property
    def max_reference_images(self) -> int:
        return 0

    @classmethod
    @abc.abstractmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        """Returns true if sufficient credentials are given to build this provider."""
        raise NotImplementedError("validate_credentials not implemented")

    @classmethod
    def build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> ImageGenerationProvider:
        if not cls.validate_credentials(credentials):
            raise ImageProviderCredentialsError(
                f"Invalid image generation credentials: {credentials}"
            )
        return cls._build_from_credentials(credentials)

    @classmethod
    @abc.abstractmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> ImageGenerationProvider:
        """
        Given credentials, builds an instance of the provider.
        Should NOT be called directly - use build_from_credentials instead.

        AssertionError if credentials are invalid.
        """
        raise NotImplementedError("build_from_credentials not implemented")

    @abc.abstractmethod
    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResponse:
        """Generates an image based on a prompt."""
        raise NotImplementedError("generate_image not implemented")
