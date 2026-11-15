from enum import Enum

from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
)
from onyx.image_gen.providers.azure_img_gen import AzureImageGenerationProvider
from onyx.image_gen.providers.litellm_img_gen import LiteLLMImageGenerationProvider
from onyx.image_gen.providers.openai_img_gen import OpenAIImageGenerationProvider
from onyx.image_gen.providers.vertex_img_gen import VertexImageGenerationProvider


class ImageGenerationProviderName(str, Enum):
    AZURE = "azure"
    OPENAI = "openai"
    VERTEX_AI = "vertex_ai"


PROVIDERS: dict[ImageGenerationProviderName, type[ImageGenerationProvider]] = {
    ImageGenerationProviderName.AZURE: AzureImageGenerationProvider,
    ImageGenerationProviderName.OPENAI: OpenAIImageGenerationProvider,
    ImageGenerationProviderName.VERTEX_AI: VertexImageGenerationProvider,
}


def get_image_generation_provider(
    provider: str,
    credentials: ImageGenerationProviderCredentials,
) -> ImageGenerationProvider:
    provider_cls = _get_dedicated_provider_cls(provider)
    if provider_cls is None:
        return LiteLLMImageGenerationProvider.build_for_provider(provider, credentials)
    return provider_cls.build_from_credentials(credentials)


def validate_credentials(
    provider: str,
    credentials: ImageGenerationProviderCredentials,
) -> bool:
    provider_cls = _get_dedicated_provider_cls(provider)
    if provider_cls is None:
        return LiteLLMImageGenerationProvider.validate_credentials(credentials)
    return provider_cls.validate_credentials(credentials)


def has_dedicated_provider(provider: str) -> bool:
    return _get_dedicated_provider_cls(provider) is not None


def _get_dedicated_provider_cls(
    provider: str,
) -> type[ImageGenerationProvider] | None:
    try:
        return PROVIDERS[ImageGenerationProviderName(provider)]
    except ValueError:
        return None
