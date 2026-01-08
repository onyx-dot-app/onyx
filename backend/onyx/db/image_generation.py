from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.models import ImageGenerationConfig
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration
from onyx.llm.utils import get_max_input_tokens
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Default image generation config constants
DEFAULT_IMAGE_PROVIDER_ID = "openai_gpt_image_1"
DEFAULT_IMAGE_MODEL_NAME = "gpt-image-1"
DEFAULT_IMAGE_PROVIDER = "openai"


def create_image_generation_config__no_commit(
    db_session: Session,
    image_provider_id: str,
    model_configuration_id: int,
    is_default: bool = False,
) -> ImageGenerationConfig:
    """Create a new image generation config."""
    # If setting as default, clear ALL existing defaults in a single atomic update
    # This is more atomic than select-then-update pattern
    if is_default:
        db_session.execute(
            update(ImageGenerationConfig)
            .where(ImageGenerationConfig.is_default.is_(True))
            .values(is_default=False)
        )

    new_config = ImageGenerationConfig(
        image_provider_id=image_provider_id,
        model_configuration_id=model_configuration_id,
        is_default=is_default,
    )
    db_session.add(new_config)
    db_session.flush()
    return new_config


def get_all_image_generation_configs(
    db_session: Session,
) -> list[ImageGenerationConfig]:
    """Get all image generation configs.

    Returns:
        List of all ImageGenerationConfig objects
    """
    stmt = select(ImageGenerationConfig)
    return list(db_session.scalars(stmt).all())


def get_image_generation_config(
    db_session: Session,
    image_provider_id: str,
) -> ImageGenerationConfig | None:
    """Get a single image generation config by image_provider_id with relationships loaded.

    Args:
        db_session: Database session
        image_provider_id: The image provider ID (primary key)

    Returns:
        The ImageGenerationConfig or None if not found
    """
    stmt = (
        select(ImageGenerationConfig)
        .where(ImageGenerationConfig.image_provider_id == image_provider_id)
        .options(
            selectinload(ImageGenerationConfig.model_configuration).selectinload(
                ModelConfiguration.llm_provider
            )
        )
    )
    return db_session.scalar(stmt)


def get_default_image_generation_config(
    db_session: Session,
) -> ImageGenerationConfig | None:
    """Get the default image generation config.

    Returns:
        The default ImageGenerationConfig or None if not set
    """
    stmt = (
        select(ImageGenerationConfig)
        .where(ImageGenerationConfig.is_default.is_(True))
        .options(
            selectinload(ImageGenerationConfig.model_configuration).selectinload(
                ModelConfiguration.llm_provider
            )
        )
    )
    return db_session.scalar(stmt)


def set_default_image_generation_config(
    db_session: Session,
    image_provider_id: str,
) -> None:
    """Set a config as the default (clears previous default).

    Args:
        db_session: Database session
        image_provider_id: The image provider ID to set as default

    Raises:
        ValueError: If config not found
    """
    # Get the config to set as default
    new_default = db_session.get(ImageGenerationConfig, image_provider_id)
    if not new_default:
        raise ValueError(
            f"ImageGenerationConfig with image_provider_id {image_provider_id} not found"
        )

    # Clear ALL existing defaults in a single atomic update
    # This is more atomic than select-then-update pattern
    db_session.execute(
        update(ImageGenerationConfig)
        .where(
            ImageGenerationConfig.is_default.is_(True),
            ImageGenerationConfig.image_provider_id != image_provider_id,
        )
        .values(is_default=False)
    )

    # Set new default
    new_default.is_default = True
    db_session.commit()


def unset_default_image_generation_config(
    db_session: Session,
    image_provider_id: str,
) -> None:
    """Unset a config as the default."""
    config = db_session.get(ImageGenerationConfig, image_provider_id)
    if not config:
        raise ValueError(
            f"ImageGenerationConfig with image_provider_id {image_provider_id} not found"
        )
    config.is_default = False
    db_session.commit()


def delete_image_generation_config__no_commit(
    db_session: Session,
    image_provider_id: str,
) -> None:
    """Delete an image generation config by image_provider_id."""
    config = db_session.get(ImageGenerationConfig, image_provider_id)
    if not config:
        raise ValueError(
            f"ImageGenerationConfig with image_provider_id {image_provider_id} not found"
        )

    db_session.delete(config)
    db_session.flush()


def create_default_image_gen_config_from_api_key(
    db_session: Session,
    api_key: str,
    provider: str = DEFAULT_IMAGE_PROVIDER,
    image_provider_id: str = DEFAULT_IMAGE_PROVIDER_ID,
    model_name: str = DEFAULT_IMAGE_MODEL_NAME,
) -> ImageGenerationConfig | None:
    """Create default image gen config using an API key directly.

    This function is used during tenant provisioning to automatically create
    a default image generation config when an OpenAI provider is configured.

    Args:
        db_session: Database session
        api_key: API key for the LLM provider
        provider: Provider name (default: openai)
        image_provider_id: Static unique key for the config (default: openai_gpt_image_1)
        model_name: Model name for image generation (default: gpt-image-1)

    Returns:
        The created ImageGenerationConfig, or None if:
        - image_generation_config table already has records
    """
    # Check if any image generation configs already exist (optimization to avoid work)
    existing_configs = get_all_image_generation_configs(db_session)
    if existing_configs:
        logger.info("Image generation config already exists, skipping default creation")
        return None

    try:
        # Create new LLM provider for image generation
        new_provider = LLMProvider(
            name=f"Image Gen - {image_provider_id}",
            provider=provider,
            api_key=api_key,
            api_base=None,
            api_version=None,
            default_model_name=model_name,
            deployment_name=None,
            is_public=True,
        )
        db_session.add(new_provider)
        db_session.flush()

        # Create model configuration
        max_input_tokens = get_max_input_tokens(
            model_name=model_name,
            model_provider=provider,
        )

        model_config = ModelConfiguration(
            llm_provider_id=new_provider.id,
            name=model_name,
            is_visible=True,
            max_input_tokens=max_input_tokens,
        )
        db_session.add(model_config)
        db_session.flush()

        # Create image generation config
        config = create_image_generation_config__no_commit(
            db_session=db_session,
            image_provider_id=image_provider_id,
            model_configuration_id=model_config.id,
            is_default=True,
        )

        db_session.commit()

        logger.info(f"Created default image generation config: {image_provider_id}")

        return config

    except Exception:
        db_session.rollback()
        logger.exception(
            f"Failed to create default image generation config {image_provider_id}"
        )
        return None
