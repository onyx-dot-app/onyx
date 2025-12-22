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


def _generate_unique_provider_name(
    db_session: Session, base_name: str, model_name: str
) -> str:
    """Generate a unique provider name for image generation.

    Tries "Image Gen - {base_name}" first, then appends numbers if needed.
    """
    # First try simple name
    candidate = f"Image Gen - {base_name}"
    existing = db_session.query(LLMProviderModel).filter_by(name=candidate).first()
    if not existing:
        return candidate

    # Try with model name
    candidate = f"Image Gen - {base_name} ({model_name})"
    existing = db_session.query(LLMProviderModel).filter_by(name=candidate).first()
    if not existing:
        return candidate

    # Append numbers until we find a unique name
    counter = 2
    while True:
        candidate = f"Image Gen - {base_name} ({model_name}) {counter}"
        existing = db_session.query(LLMProviderModel).filter_by(name=candidate).first()
        if not existing:
            return candidate
        counter += 1


@admin_router.post("/test")
def test_image_generation(
    test_request: TestImageGenerationRequest,
    _: User | None = Depends(current_admin_user),
) -> None:
    """Test if an API key is valid for image generation.

    Makes a minimal image generation request to verify credentials using LiteLLM.
    """
    from litellm import image_generation

    try:
        if test_request.provider == "azure":
            if not test_request.api_base or not test_request.api_version:
                raise HTTPException(
                    status_code=400,
                    detail="api_base and api_version are required for Azure",
                )

            # For Azure, use deployment_name if provided, otherwise use model_name
            deployment = test_request.deployment_name or test_request.model_name
            model = f"azure/{deployment}"

            # Make a minimal image generation request using LiteLLM
            image_generation(
                prompt="test",
                model=model,
                api_key=test_request.api_key,
                api_base=test_request.api_base,
                api_version=test_request.api_version,
                size="1024x1024",
                n=1,
            )
        else:
            # OpenAI or other providers
            image_generation(
                prompt="test",
                model=test_request.model_name,
                api_key=test_request.api_key,
                api_base=test_request.api_base or None,
                size="1024x1024",
                n=1,
            )

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.warning(f"Image generation test failed: {error_msg}")

        # Extract meaningful error message
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Invalid API key")
        elif "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
            raise HTTPException(
                status_code=400, detail=f"Model '{test_request.model_name}' not found"
            )
        elif "permission" in error_msg.lower() or "access" in error_msg.lower():
            raise HTTPException(
                status_code=403,
                detail="API key does not have permission for image generation",
            )
        else:
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
       → Extract credentials from existing provider, create new provider

    2. New credentials mode: api_key + provider provided
       → Create new provider with given credentials
    """
    try:
        if config_create.source_llm_provider_id is not None:
            # Clone mode: Extract credentials from source provider
            source_provider = db_session.get(
                LLMProviderModel, config_create.source_llm_provider_id
            )
            if not source_provider:
                raise HTTPException(
                    status_code=404,
                    detail=f"Source LLM provider with id {config_create.source_llm_provider_id} not found",
                )

            # Generate unique name for the new provider
            new_provider_name = _generate_unique_provider_name(
                db_session, source_provider.name, config_create.model_name
            )

            # Create new LLM provider with same credentials
            new_provider_request = LLMProviderUpsertRequest(
                name=new_provider_name,
                provider=source_provider.provider,
                api_key=source_provider.api_key,
                api_base=source_provider.api_base,
                api_version=source_provider.api_version,
                custom_config=source_provider.custom_config,
                default_model_name=config_create.model_name,
                deployment_name=source_provider.deployment_name,
                is_public=True,
                groups=[],
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name=config_create.model_name,
                        is_visible=True,
                    )
                ],
            )

        elif config_create.api_key is not None and config_create.provider is not None:
            # New credentials mode: Use provided credentials
            new_provider_name = _generate_unique_provider_name(
                db_session,
                f"{config_create.provider.title()} Provider",
                config_create.model_name,
            )

            new_provider_request = LLMProviderUpsertRequest(
                name=new_provider_name,
                provider=config_create.provider,
                api_key=config_create.api_key,
                api_base=config_create.api_base,
                api_version=config_create.api_version,
                default_model_name=config_create.model_name,
                deployment_name=config_create.deployment_name,
                is_public=True,
                groups=[],
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name=config_create.model_name,
                        is_visible=True,
                    )
                ],
            )

        else:
            raise HTTPException(
                status_code=400,
                detail="Either source_llm_provider_id or (api_key + provider) must be provided",
            )

        # Create the new LLM provider
        new_provider = upsert_llm_provider(new_provider_request, db_session)

        # Query database directly to get model configuration ID
        model_config = (
            db_session.query(ModelConfiguration)
            .filter(
                ModelConfiguration.llm_provider_id == new_provider.id,
                ModelConfiguration.name == config_create.model_name,
            )
            .first()
        )

        if not model_config:
            raise HTTPException(
                status_code=500,
                detail="Failed to create model configuration for new provider",
            )
        model_configuration_id = model_config.id

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

        # 2. Build request for new LLM provider (same logic as create)
        if config_update.source_llm_provider_id is not None:
            # Clone mode: Extract credentials from source provider
            source_provider = db_session.get(
                LLMProviderModel, config_update.source_llm_provider_id
            )
            if not source_provider:
                raise HTTPException(
                    status_code=404,
                    detail=f"Source LLM provider with id {config_update.source_llm_provider_id} not found",
                )

            new_provider_name = _generate_unique_provider_name(
                db_session, source_provider.name, config_update.model_name
            )

            new_provider_request = LLMProviderUpsertRequest(
                name=new_provider_name,
                provider=source_provider.provider,
                api_key=source_provider.api_key,
                api_base=source_provider.api_base,
                api_version=source_provider.api_version,
                custom_config=source_provider.custom_config,
                default_model_name=config_update.model_name,
                deployment_name=source_provider.deployment_name,
                is_public=True,
                groups=[],
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name=config_update.model_name,
                        is_visible=True,
                    )
                ],
            )

        elif config_update.api_key is not None and config_update.provider is not None:
            # New credentials mode
            new_provider_name = _generate_unique_provider_name(
                db_session,
                f"{config_update.provider.title()} Provider",
                config_update.model_name,
            )

            new_provider_request = LLMProviderUpsertRequest(
                name=new_provider_name,
                provider=config_update.provider,
                api_key=config_update.api_key,
                api_base=config_update.api_base,
                api_version=config_update.api_version,
                default_model_name=config_update.model_name,
                deployment_name=config_update.deployment_name,
                is_public=True,
                groups=[],
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name=config_update.model_name,
                        is_visible=True,
                    )
                ],
            )

        else:
            raise HTTPException(
                status_code=400,
                detail="Either source_llm_provider_id or (api_key + provider) must be provided",
            )

        # 3. Create the new LLM provider
        new_provider = upsert_llm_provider(new_provider_request, db_session)

        # Get model configuration ID from new provider
        new_model_config = (
            db_session.query(ModelConfiguration)
            .filter(
                ModelConfiguration.llm_provider_id == new_provider.id,
                ModelConfiguration.name == config_update.model_name,
            )
            .first()
        )

        if not new_model_config:
            raise HTTPException(
                status_code=500,
                detail="Failed to create model configuration for new provider",
            )

        # 4. Update the ImageGenerationConfig to point to new model config
        existing_config.model_configuration_id = new_model_config.id
        db_session.commit()

        # 5. Delete old LLM provider (it was exclusively for image gen)
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
