from enum import Enum

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.providers.azure_img_gen import AzureImageGenerationProvider
from onyx.image_gen.providers.openai_img_gen import OpenAIImageGenerationProvider


class ImageGenerationProviderName(str, Enum):
    AZURE = "azure"
    OPENAI = "openai"


PROVIDERS: dict[ImageGenerationProviderName, type[ImageGenerationProvider]] = {
    ImageGenerationProviderName.AZURE: AzureImageGenerationProvider,
    ImageGenerationProviderName.OPENAI: OpenAIImageGenerationProvider,
}


def get_image_generation_provider(
    provider: str,
    credentials: ImageGenerationProviderCredentials,
) -> ImageGenerationProvider:
    provider_cls = _get_provider_cls(provider)
    return provider_cls.build_from_credentials(credentials)


def validate_credentials(
    provider: str,
    credentials: ImageGenerationProviderCredentials,
) -> bool:
    provider_cls = _get_provider_cls(provider)
    return provider_cls.validate_credentials(credentials)


def _get_provider_cls(provider: str) -> type[ImageGenerationProvider]:
    try:
        provider_enum = ImageGenerationProviderName(provider)
    except ValueError:
        raise ValueError(f"Invalid image generation provider: {provider}")
    return PROVIDERS[provider_enum]
