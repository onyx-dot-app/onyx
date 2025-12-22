from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.models import ImageGenerationConfig
from onyx.db.models import ModelConfiguration


def create_image_generation_config(
    db_session: Session,
    image_provider_id: str,
    model_configuration_id: int,
    is_default: bool = False,
) -> ImageGenerationConfig:
    """Create a new image generation config.

    Args:
        db_session: Database session
        image_provider_id: Static unique key for UI-DB mapping
        model_configuration_id: ID of the model configuration to use
        is_default: Whether this should be the default config

    Returns:
        The created ImageGenerationConfig
    """
    # If setting as default, clear any existing default
    if is_default:
        existing_default = db_session.scalar(
            select(ImageGenerationConfig).where(
                ImageGenerationConfig.is_default.is_(True)
            )
        )
        if existing_default:
            existing_default.is_default = False

    new_config = ImageGenerationConfig(
        image_provider_id=image_provider_id,
        model_configuration_id=model_configuration_id,
        is_default=is_default,
    )
    db_session.add(new_config)
    db_session.commit()
    db_session.refresh(new_config)
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

    # Clear existing default
    existing_default = db_session.scalar(
        select(ImageGenerationConfig).where(ImageGenerationConfig.is_default.is_(True))
    )
    if existing_default and existing_default.image_provider_id != image_provider_id:
        existing_default.is_default = False
        db_session.flush()

    # Set new default
    new_default.is_default = True
    db_session.commit()


def delete_image_generation_config(
    db_session: Session,
    image_provider_id: str,
) -> None:
    """Delete an image generation config by image_provider_id.

    Args:
        db_session: Database session
        image_provider_id: The image provider ID to delete

    Raises:
        ValueError: If config not found
    """
    config = db_session.get(ImageGenerationConfig, image_provider_id)
    if not config:
        raise ValueError(
            f"ImageGenerationConfig with image_provider_id {image_provider_id} not found"
        )

    db_session.delete(config)
    db_session.commit()
