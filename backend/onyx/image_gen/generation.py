from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.image_generation import get_default_image_generation_config
from onyx.image_gen.exceptions import ImageGenerationNotConfiguredError
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.factory import validate_credentials
from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ImageShape
from onyx.image_gen.interfaces import ReferenceImage
from onyx.utils.logger import setup_logger

logger = setup_logger()

_GPT_IMAGE_PREFIX = "gpt-image-"


class GeneratedImageData(BaseModel):
    b64_data: str
    revised_prompt: str


def resolve_image_size(model: str, shape: ImageShape) -> str:
    is_gpt_image = _GPT_IMAGE_PREFIX in model
    if shape == ImageShape.LANDSCAPE:
        return "1536x1024" if is_gpt_image else "1792x1024"
    if shape == ImageShape.PORTRAIT:
        return "1024x1536" if is_gpt_image else "1024x1792"
    return "1024x1024"


def response_format_for_model(model: str) -> str | None:
    """gpt-image-* models reject the ``response_format`` param; every other
    model needs ``b64_json`` to return base64 inline."""
    return None if _GPT_IMAGE_PREFIX in model else "b64_json"


def generate_images_with_provider(
    provider: ImageGenerationProvider,
    model: str,
    prompt: str,
    size: str,
    n: int = 1,
    quality: str | None = None,
    reference_images: list[ReferenceImage] | None = None,
) -> list[GeneratedImageData]:
    response = provider.generate_image(
        prompt=prompt,
        model=model,
        size=size,
        n=n,
        quality=quality,
        reference_images=reference_images,
        response_format=response_format_for_model(model),
    )

    if not response.data:
        raise RuntimeError("No image data returned from the provider.")

    results: list[GeneratedImageData] = []
    for item in response.data:
        dumped = item.model_dump()
        b64 = dumped.get("b64_json")
        if not b64:
            continue
        results.append(
            GeneratedImageData(
                b64_data=b64,
                revised_prompt=dumped.get("revised_prompt") or prompt,
            )
        )

    if not results:
        raise RuntimeError("No base64 image data returned from the provider.")
    return results


def _default_provider_and_model(
    db_session: Session,
) -> tuple[str, str, ImageGenerationProviderCredentials]:
    config = get_default_image_generation_config(db_session)
    if (
        not config
        or not config.model_configuration
        or not config.model_configuration.llm_provider
    ):
        raise ImageGenerationNotConfiguredError(
            "No default image generation provider is configured."
        )

    llm_provider = config.model_configuration.llm_provider
    credentials = ImageGenerationProviderCredentials(
        api_key=(
            llm_provider.api_key.get_value(apply_mask=False)
            if llm_provider.api_key
            else None
        ),
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        deployment_name=llm_provider.deployment_name,
        custom_config=llm_provider.custom_config,
    )
    if not validate_credentials(llm_provider.provider, credentials):
        raise ImageGenerationNotConfiguredError(
            "The configured image generation provider has invalid credentials."
        )
    return llm_provider.provider, config.model_configuration.name, credentials


def is_image_generation_configured(db_session: Session) -> bool:
    try:
        _default_provider_and_model(db_session)
        return True
    except ImageGenerationNotConfiguredError:
        return False


def generate_images_with_default_config(
    prompt: str,
    shape: ImageShape = ImageShape.SQUARE,
    n: int = 1,
    quality: str | None = None,
    reference_images: list[ReferenceImage] | None = None,
) -> list[GeneratedImageData]:
    # Resolve provider/model/credentials in a short-lived session and release it
    # before the (slow, minutes-long) provider call, so a pooled DB connection
    # isn't pinned for the whole generation round-trip.
    with get_session_with_current_tenant() as db_session:
        provider_name, model, credentials = _default_provider_and_model(db_session)
    provider = get_image_generation_provider(provider_name, credentials)

    if reference_images and not provider.supports_reference_images:
        raise ValueError(
            f"Provider '{provider_name}' does not support image edits / reference images."
        )

    size = resolve_image_size(model, shape)
    logger.debug(
        "Generating %d image(s) with provider=%s model=%s size=%s",
        n,
        provider_name,
        model,
        size,
    )

    return generate_images_with_provider(
        provider=provider,
        model=model,
        prompt=prompt,
        size=size,
        n=n,
        quality=quality,
        reference_images=reference_images,
    )
