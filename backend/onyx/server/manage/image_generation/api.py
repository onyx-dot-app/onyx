from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.image_generation import create_image_generation_config
from onyx.db.image_generation import delete_image_generation_config
from onyx.db.image_generation import get_all_image_generation_configs
from onyx.db.image_generation import get_image_generation_config
from onyx.db.image_generation import set_default_image_generation_config
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import ModelConfiguration
from onyx.db.models import User
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


def _build_llm_provider_request(
    db_session: Session,
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
            name=f"Image Gen - {model_name}",
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
            name=f"Image Gen - {model_name}",
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


def _create_llm_provider_and_get_model_config_id(
    db_session: Session,
    provider_request: LLMProviderUpsertRequest,
    model_name: str,
) -> int:
    """Create LLM provider and return the model configuration ID."""
    new_provider = upsert_llm_provider(provider_request, db_session)

    model_config = (
        db_session.query(ModelConfiguration)
        .filter(
            ModelConfiguration.llm_provider_id == new_provider.id,
            ModelConfiguration.name == model_name,
        )
        .first()
    )

    if not model_config:
        raise HTTPException(
            status_code=500,
            detail="Failed to create model configuration for new provider",
        )

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
            )
        else:
            # OpenAI or other providers
            image_generation(
                prompt="a simple blue circle on white background",
                model=test_request.model_name,
                api_key=api_key,
                api_base=test_request.api_base or None,
                size="1024x1024",
                n=1,
            )

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.warning(f"Image generation test failed: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)


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
    try:
        # Build and create LLM provider
        provider_request = _build_llm_provider_request(
            db_session=db_session,
            model_name=config_create.model_name,
            source_llm_provider_id=config_create.source_llm_provider_id,
            provider=config_create.provider,
            api_key=config_create.api_key,
            api_base=config_create.api_base,
            api_version=config_create.api_version,
            deployment_name=config_create.deployment_name,
        )

        model_configuration_id = _create_llm_provider_and_get_model_config_id(
            db_session=db_session,
            provider_request=provider_request,
            model_name=config_create.model_name,
        )

        # Create the ImageGenerationConfig
        config = create_image_generation_config(
            db_session=db_session,
            model_configuration_id=model_configuration_id,
            is_default=config_create.is_default,
        )
        # Refresh to load relationships
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


@admin_router.get("/config/{config_id}/credentials")
def get_config_credentials(
    config_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ImageGenerationCredentials:
    """Get the credentials for an image generation config (for edit mode).

    Returns the unmasked API key and other credential fields.
    """
    config = get_image_generation_config(db_session, config_id)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"ImageGenerationConfig with id {config_id} not found",
        )

    return ImageGenerationCredentials.from_model(config)


@admin_router.put("/config/{config_id}")
def update_config(
    config_id: int,
    config_update: ImageGenerationConfigUpdate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ImageGenerationConfigView:
    """Update an image generation configuration.

    Flow:
    1. Get existing config and its LLM provider
    2. Create new LLM provider + model config (same as create flow)
    3. Update ImageGenerationConfig to point to new model config
    4. Delete old LLM provider
    """
    try:
        # 1. Get existing config
        existing_config = get_image_generation_config(db_session, config_id)
        if not existing_config:
            raise HTTPException(
                status_code=404,
                detail=f"ImageGenerationConfig with id {config_id} not found",
            )

        old_llm_provider_id = existing_config.model_configuration.llm_provider_id

        # 2. Build and create new LLM provider
        provider_request = _build_llm_provider_request(
            db_session=db_session,
            model_name=config_update.model_name,
            source_llm_provider_id=config_update.source_llm_provider_id,
            provider=config_update.provider,
            api_key=config_update.api_key,
            api_base=config_update.api_base,
            api_version=config_update.api_version,
            deployment_name=config_update.deployment_name,
        )

        new_model_config_id = _create_llm_provider_and_get_model_config_id(
            db_session=db_session,
            provider_request=provider_request,
            model_name=config_update.model_name,
        )

        # 3. Update the ImageGenerationConfig to point to new model config
        existing_config.model_configuration_id = new_model_config_id
        db_session.commit()

        # 4. Delete old LLM provider (it was exclusively for image gen)
        remove_llm_provider(db_session, old_llm_provider_id)

        # Refresh to load relationships
        db_session.refresh(existing_config)
        return ImageGenerationConfigView.from_model(existing_config)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.delete("/config/{config_id}")
def delete_config(
    config_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an image generation configuration."""
    try:
        delete_image_generation_config(db_session, config_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/config/{config_id}/default")
def set_config_as_default(
    config_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Set a configuration as the default for image generation."""
    try:
        set_default_image_generation_config(db_session, config_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
