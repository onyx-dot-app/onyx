from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.image_generation import create_image_generation_config__no_commit
from onyx.db.image_generation import delete_image_generation_config__no_commit
from onyx.db.image_generation import get_all_image_generation_configs
from onyx.db.image_generation import get_image_generation_config
from onyx.db.image_generation import set_default_image_generation_config
from onyx.db.image_generation import unset_default_image_generation_config
from onyx.db.llm import remove_llm_provider__no_commit
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import ModelConfiguration
from onyx.db.models import User
from onyx.llm.utils import get_max_input_tokens
from onyx.server.manage.image_generation.models import ImageGenerationConfigCreate
from onyx.server.manage.image_generation.models import ImageGenerationConfigUpdate
from onyx.server.manage.image_generation.models import ImageGenerationConfigView
from onyx.server.manage.image_generation.models import ImageGenerationCredentials
from onyx.server.manage.image_generation.models import TestImageGenerationRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/image-generation")


def _get_test_quality_for_model(model_name: str) -> str | None:
    """Returns the fastest quality setting for credential testing.

    - gpt-image-1: 'low' (fastest)
    - dall-e-3: 'standard' (faster than 'hd')
    - Other models: None (use API default)
    """
    model_lower = model_name.lower()

    if "gpt-image-1" in model_lower:
        return "low"
    elif "dall-e-3" in model_lower or "dalle-3" in model_lower:
        return "standard"
    return None


def _build_llm_provider_request(
    db_session: Session,
    image_provider_id: str,
    model_name: str,
    source_llm_provider_id: int | None,
    provider: str | None,
    api_key: str | None,
    api_base: str | None,
    api_version: str | None,
    deployment_name: str | None,
) -> LLMProviderUpsertRequest:
    """Build LLM provider request for image generation config.

    Supports two modes:
    1. Clone mode: source_llm_provider_id provided - uses API key from source
    2. New credentials mode: api_key + provider provided

    """
    if source_llm_provider_id is not None:
        # Clone mode: Only use API key from source provider
        source_provider = db_session.get(LLMProviderModel, source_llm_provider_id)
        if not source_provider:
            raise HTTPException(
                status_code=404,
                detail=f"Source LLM provider with id {source_llm_provider_id} not found",
            )

        return LLMProviderUpsertRequest(
            name=f"Image Gen - {image_provider_id}",
            provider=source_provider.provider,
            api_key=source_provider.api_key,  # Only this from source
            api_base=api_base,  # From request
            api_version=api_version,  # From request
            default_model_name=model_name,
            deployment_name=deployment_name,  # From request
            is_public=True,
            groups=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=model_name,
                    is_visible=True,
                )
            ],
        )

    elif api_key is not None and provider is not None:
        # New credentials mode
        return LLMProviderUpsertRequest(
            name=f"Image Gen - {image_provider_id}",
            provider=provider,
            api_key=api_key,
            api_base=api_base,
            api_version=api_version,
            default_model_name=model_name,
            deployment_name=deployment_name,
            is_public=True,
            groups=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=model_name,
                    is_visible=True,
                )
            ],
        )

    else:
        raise HTTPException(
            status_code=400,
            detail="Either source_llm_provider_id or (api_key + provider) must be provided",
        )


def _create_image_gen_llm_provider__no_commit(
    db_session: Session,
    provider_request: LLMProviderUpsertRequest,
    model_name: str,
) -> int:
    """Create a new LLM provider for image generation. Returns model_config_id.

    Unlike upsert_llm_provider, this always creates a new provider and never
    deletes existing model configurations (which would cascade-delete ImageGenerationConfig).
    """

    # Always create a new provider (don't look up by name to avoid upsert behavior)
    new_provider = LLMProviderModel(
        name=provider_request.name,
        provider=provider_request.provider,
        api_key=provider_request.api_key,
        api_base=provider_request.api_base,
        api_version=provider_request.api_version,
        default_model_name=provider_request.default_model_name,
        deployment_name=provider_request.deployment_name,
        is_public=provider_request.is_public,
    )
    db_session.add(new_provider)
    db_session.flush()  # Get the ID

    # Create model configuration
    max_input_tokens = get_max_input_tokens(
        model_name=model_name,
        model_provider=provider_request.provider,
    )

    model_config = ModelConfiguration(
        llm_provider_id=new_provider.id,
        name=model_name,
        is_visible=True,
        max_input_tokens=max_input_tokens,
    )
    db_session.add(model_config)
    db_session.flush()

    return model_config.id


@admin_router.post("/test")
def test_image_generation(
    test_request: TestImageGenerationRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Test if an API key is valid for image generation.

    Makes a minimal image generation request to verify credentials using LiteLLM.

    Two modes:
    1. Direct: api_key + provider provided
    2. From existing provider: source_llm_provider_id provided (fetches API key from DB)
    """
    from litellm import image_generation

    # Resolve API key and provider
    if test_request.source_llm_provider_id is not None:
        # Fetch API key from existing provider
        source_provider = db_session.get(
            LLMProviderModel, test_request.source_llm_provider_id
        )
        if not source_provider:
            raise HTTPException(
                status_code=404,
                detail=f"Source LLM provider with id {test_request.source_llm_provider_id} not found",
            )
        api_key = source_provider.api_key
        provider = source_provider.provider
    elif test_request.api_key is not None and test_request.provider is not None:
        # Use directly provided credentials
        api_key = test_request.api_key
        provider = test_request.provider
    else:
        raise HTTPException(
            status_code=400,
            detail="Either source_llm_provider_id or (api_key + provider) must be provided",
        )
    # Use lowest quality for faster testing
    quality = _get_test_quality_for_model(test_request.model_name)
    try:
        if provider == "azure":
            if not test_request.api_base or not test_request.api_version:
                raise HTTPException(
                    status_code=400,
                    detail="api_base and api_version are required for Azure",
                )

            # For Azure, use deployment_name if provided, otherwise use model_name
            deployment = test_request.deployment_name or test_request.model_name
            model = f"azure/{deployment}"

            # Make a minimal image generation request using LiteLLM
            # Use descriptive prompt to avoid Azure content policy rejection
            image_generation(
                prompt="a simple blue circle on white background",
                model=model,
                api_key=api_key,
                api_base=test_request.api_base,
                api_version=test_request.api_version,
                size="1024x1024",
                n=1,
                quality=quality,
            )
        else:
            image_generation(
                prompt="a simple blue circle on white background",
                model=test_request.model_name,
                api_key=api_key,
                api_base=test_request.api_base or None,
                size="1024x1024",
                n=1,
                quality=quality,
            )

    except HTTPException:
        raise
    except Exception as e:
        # Log only exception type to avoid exposing sensitive data
        # (LiteLLM errors may contain URLs with API keys or auth tokens)
        logger.warning(f"Image generation test failed: {type(e).__name__}")
        raise HTTPException(
            status_code=400,
            detail=f"Image generation test failed: {type(e).__name__}",
        )


@admin_router.post("/config")
def create_config(
    config_create: ImageGenerationConfigCreate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ImageGenerationConfigView:
    """Create a new image generation configuration.

    Both modes create a new LLM provider + model config + image config:

    1. Clone mode: source_llm_provider_id provided
       → Extract api key from existing provider, create new provider

    2. New credentials mode: api_key + provider provided
       → Create new provider with given credentials
    """
    # Check if image_provider_id already exists
    existing_config = get_image_generation_config(
        db_session, config_create.image_provider_id
    )
    if existing_config:
        raise HTTPException(
            status_code=400,
            detail=f"ImageGenerationConfig with image_provider_id '{config_create.image_provider_id}' already exists",
        )

    try:
        # Build and create LLM provider
        provider_request = _build_llm_provider_request(
            db_session=db_session,
            image_provider_id=config_create.image_provider_id,
            model_name=config_create.model_name,
            source_llm_provider_id=config_create.source_llm_provider_id,
            provider=config_create.provider,
            api_key=config_create.api_key,
            api_base=config_create.api_base,
            api_version=config_create.api_version,
            deployment_name=config_create.deployment_name,
        )

        model_configuration_id = _create_image_gen_llm_provider__no_commit(
            db_session=db_session,
            provider_request=provider_request,
            model_name=config_create.model_name,
        )

        # Create the ImageGenerationConfig
        config = create_image_generation_config__no_commit(
            db_session=db_session,
            image_provider_id=config_create.image_provider_id,
            model_configuration_id=model_configuration_id,
            is_default=config_create.is_default,
        )
        db_session.commit()
        db_session.refresh(config)
        return ImageGenerationConfigView.from_model(config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.get("/config")
def get_all_configs(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ImageGenerationConfigView]:
    """Get all image generation configurations."""
    configs = get_all_image_generation_configs(db_session)
    return [ImageGenerationConfigView.from_model(config) for config in configs]


@admin_router.get("/config/{image_provider_id}/credentials")
def get_config_credentials(
    image_provider_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ImageGenerationCredentials:
    """Get the credentials for an image generation config (for edit mode).

    Returns the unmasked API key and other credential fields.
    """
    config = get_image_generation_config(db_session, image_provider_id)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"ImageGenerationConfig with image_provider_id {image_provider_id} not found",
        )

    return ImageGenerationCredentials.from_model(config)


@admin_router.put("/config/{image_provider_id}")
def update_config(
    image_provider_id: str,
    config_update: ImageGenerationConfigUpdate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ImageGenerationConfigView:
    """Update an image generation configuration.

    Flow:
    1. Get existing config and its LLM provider
    2. Rename old LLM provider to free up the name (avoids unique constraint)
    3. Create new LLM provider + model config (same as create flow)
    4. Update ImageGenerationConfig to point to new model config
    5. Delete old LLM provider (safe now - nothing references it)
    """
    try:
        # 1. Get existing config
        existing_config = get_image_generation_config(db_session, image_provider_id)
        if not existing_config:
            raise HTTPException(
                status_code=404,
                detail=f"ImageGenerationConfig with image_provider_id {image_provider_id} not found",
            )

        old_llm_provider_id = existing_config.model_configuration.llm_provider_id

        # 2. Rename old LLM provider to free up the name
        # (Can't delete first due to cascade: LLMProvider -> ModelConfig -> ImageGenConfig)
        old_provider = db_session.get(LLMProviderModel, old_llm_provider_id)
        if old_provider:
            old_provider.name = f"{old_provider.name}-old-{old_llm_provider_id}"
            db_session.flush()

        # Determine actual API key to use:
        # - Clone mode (source_llm_provider_id): API key comes from source provider
        # - New credentials mode: Use provided api_key, or preserve existing if not changed
        actual_api_key = config_update.api_key
        if config_update.source_llm_provider_id is None and old_provider:
            # Check if we should preserve existing API key:
            # - api_key_changed=False AND (key is None/empty OR looks masked)
            provided_key_is_masked = (
                config_update.api_key and "****" in config_update.api_key
            )
            if not config_update.api_key_changed and (
                not config_update.api_key or provided_key_is_masked
            ):
                # Preserve existing API key when user didn't change it
                actual_api_key = old_provider.api_key

        # 3. Build and create new LLM provider
        provider_request = _build_llm_provider_request(
            db_session=db_session,
            image_provider_id=image_provider_id,
            model_name=config_update.model_name,
            source_llm_provider_id=config_update.source_llm_provider_id,
            provider=config_update.provider,
            api_key=actual_api_key,
            api_base=config_update.api_base,
            api_version=config_update.api_version,
            deployment_name=config_update.deployment_name,
        )

        new_model_config_id = _create_image_gen_llm_provider__no_commit(
            db_session=db_session,
            provider_request=provider_request,
            model_name=config_update.model_name,
        )

        # 4. Update the ImageGenerationConfig to point to new model config
        existing_config.model_configuration_id = new_model_config_id

        # 5. Delete old LLM provider (safe now - nothing references it)
        remove_llm_provider__no_commit(db_session, old_llm_provider_id)

        db_session.commit()
        db_session.refresh(existing_config)
        return ImageGenerationConfigView.from_model(existing_config)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.delete("/config/{image_provider_id}")
def delete_config(
    image_provider_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an image generation configuration and its associated LLM provider."""
    try:
        # Get the config first to find the associated LLM provider
        existing_config = get_image_generation_config(db_session, image_provider_id)
        if not existing_config:
            raise HTTPException(
                status_code=404,
                detail=f"ImageGenerationConfig with image_provider_id {image_provider_id} not found",
            )

        llm_provider_id = existing_config.model_configuration.llm_provider_id

        # Delete the image generation config first
        delete_image_generation_config__no_commit(db_session, image_provider_id)

        # Clean up the orphaned LLM provider (it was exclusively for image gen)
        remove_llm_provider__no_commit(db_session, llm_provider_id)

        db_session.commit()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/config/{image_provider_id}/default")
def set_config_as_default(
    image_provider_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Set a configuration as the default for image generation."""
    try:
        set_default_image_generation_config(db_session, image_provider_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.delete("/config/{image_provider_id}/default")
def unset_config_as_default(
    image_provider_id: str,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Unset a configuration as the default for image generation."""
    try:
        unset_default_image_generation_config(db_session, image_provider_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
