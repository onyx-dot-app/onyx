from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.providers.azure_img_gen import AzureImageGenerationProvider
from onyx.image_gen.providers.openai_img_gen import OpenAIImageGenerationProvider


def get_image_generation_provider(
    provider: str,
    credentials: ImageGenerationProviderCredentials,
) -> ImageGenerationProvider:
    if provider == "azure":
        return AzureImageGenerationProvider.build_from_credentials(credentials)
    elif provider == "openai":
        return OpenAIImageGenerationProvider.build_from_credentials(credentials)
    else:
        raise ValueError(f"Invalid image generation provider: {provider}")
