import abc
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel


if TYPE_CHECKING:
    from litellm.types.utils import ImageResponse as ImageGenerationResponse


class ImageGenerationProviderCredentials(BaseModel):
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
    custom_config: dict[str, str] | None = None


class ImageGenerationProvider(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> "ImageGenerationProvider":
        raise NotImplementedError("No credentials provided")

    @abc.abstractmethod
    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        **kwargs: Any,
    ) -> "ImageGenerationResponse":
        raise NotImplementedError("No image generation response provided")
