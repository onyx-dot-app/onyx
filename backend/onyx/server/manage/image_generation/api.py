from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.api_token import assign_api_token, peek_api_token_value
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.image_generation import (
    create_image_generation_config__no_commit,
    delete_image_generation_config__no_commit,
    get_all_image_generation_configs,
    get_image_generation_config,
    set_default_image_generation_config,
    unset_default_image_generation_config,
)
from onyx.db.llm import remove_llm_provider
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import ModelConfiguration, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.factory import get_image_generation_provider, validate_credentials
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.llm.exceptions import litellm_exception_to_safe_error
from onyx.llm.model_capabilities import get_max_input_tokens
from onyx.llm.utils import collect_credential_values
from onyx.server.manage.api_token.models import ApiTokenInput, ExistingApiToken
from onyx.server.manage.image_generation.models import (
    ImageGenerationConfigCreate,
    ImageGenerationConfigUpdate,
    ImageGenerationConfigView,
    ImageGenerationCredentials,
    TestImageGenerationRequest,
)
from onyx.server.manage.llm.api import (
    _validate_and_normalize_vertex_auth,
    _validate_llm_provider_change,
)
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from onyx.server.manage.llm.provider_cache import invalidate_provider_listing_cache
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/image-generation")


def _get_test_quality_for_model(model_name: str) -> str | None:
    """Returns the fastest quality setting for credential testing.

    - gpt-image-*: 'low' (fastest)
    - Other models: None (use API default)
    """
    model_lower = model_name.lower()

    if "gpt-image-" in model_lower:
        return "low"
    return None


def _build_llm_provider_request(
    db_session: Session,
    image_provider_id: str,
    model_name: str,
    provider: str | None,
    api_key: ApiTokenInput | None,
    api_base: str | None,
    api_version: str | None,
    deployment_name: str | None,
    custom_config: dict[str, str] | None,
    current_token_id: int | None = None,
) -> LLMProviderUpsertRequest:
    """Build the LLM provider request for an image generation config.

    ``current_token_id`` is the key of the config being edited, if any."""
    if not provider:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "No provider provided")

    custom_config = _validate_and_normalize_vertex_auth(provider, custom_config)

    credentials = ImageGenerationProviderCredentials(
        api_key=peek_api_token_value(
            db_session,
            api_key,
            platform=provider,
            base_url=api_base,
            current_token_id=current_token_id,
        ),
        api_base=api_base,
        api_version=api_version,
        deployment_name=deployment_name,
        custom_config=custom_config,
    )

    if not validate_credentials(provider, credentials):
        raise HTTPException(
            status_code=400,
            detail=f"Incorrect credentials for {provider}",
        )

    return LLMProviderUpsertRequest(
        name=f"Image Gen - {image_provider_id}",
        provider=provider,
        api_key=api_key,
        api_base=api_base,
        api_version=api_version,
        deployment_name=deployment_name,
        is_public=True,
        groups=[],
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=model_name,
                is_visible=True,
            )
        ],
        custom_config=custom_config,
    )


def _create_image_gen_llm_provider__no_commit(
    db_session: Session,
    provider_request: LLMProviderUpsertRequest,
    model_name: str,
    current_token_id: int | None = None,
) -> int:
    """Create a new LLM provider for image generation. Returns model_config_id.

    Unlike upsert_llm_provider, this always creates a new provider and never
    deletes existing model configurations (which would cascade-delete ImageGenerationConfig).
    ``current_token_id`` is the key of the provider this one replaces, so an
    edit can keep it.
    """

    # Always create a new provider (don't look up by name to avoid upsert behavior)
    new_provider = LLMProviderModel(
        name=provider_request.name,
        provider=provider_request.provider,
        api_token_id=current_token_id,
        api_base=provider_request.api_base,
        api_version=provider_request.api_version,
        deployment_name=provider_request.deployment_name,
        is_public=provider_request.is_public,
        custom_config=provider_request.custom_config,
    )
    db_session.add(new_provider)
    db_session.flush()  # Get the ID
    assign_api_token(
        db_session,
        new_provider,
        provider_request.api_key,
        platform=provider_request.provider,
        base_url=provider_request.api_base,
    )

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
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Test if an API key is valid for image generation.

    Makes a minimal image generation request to verify credentials using LiteLLM.
    """
    provider = test_request.provider

    if provider is None:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "No provider provided")

    api_key = peek_api_token_value(
        db_session,
        test_request.api_key,
        platform=provider,
        base_url=test_request.api_base,
    )

    custom_config = _validate_and_normalize_vertex_auth(
        provider, test_request.custom_config
    )

    try:
        # Build image provider from credentials
        # If incorrect credentials are provided, this will raise an exception
        image_provider = get_image_generation_provider(
            provider=provider,
            credentials=ImageGenerationProviderCredentials(
                api_key=api_key,
                api_base=test_request.api_base,
                api_version=test_request.api_version,
                deployment_name=(
                    test_request.deployment_name or test_request.model_name
                ),
                custom_config=custom_config,
            ),
        )
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Invalid image generation provider: {provider}",
        )
    except ImageProviderCredentialsError:
        raise HTTPException(
            status_code=401,
            detail="Invalid image generation credentials",
        )

    quality = _get_test_quality_for_model(test_request.model_name)
    try:
        image_provider.generate_image(
            prompt="a simple blue circle on white background",
            model=test_request.model_name,
            size="1024x1024",
            n=1,
            quality=quality,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Image generation test failed: %s", type(e).__name__)
        safe_error = litellm_exception_to_safe_error(
            e, secrets=collect_credential_values(api_key, custom_config)
        )
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, safe_error.message)


@admin_router.post("/config")
def create_config(
    config_create: ImageGenerationConfigCreate,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ImageGenerationConfigView:
    """Create a new image generation configuration.

    Creates a new LLM provider + model config + image config with the given
    credentials.
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
            provider=config_create.provider,
            api_key=config_create.api_key,
            api_base=config_create.api_base,
            api_version=config_create.api_version,
            deployment_name=config_create.deployment_name,
            custom_config=config_create.custom_config,
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
        invalidate_provider_listing_cache()
        db_session.refresh(config)
        return ImageGenerationConfigView.from_model(config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.get("/config")
def get_all_configs(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ImageGenerationConfigView]:
    """Get all image generation configurations."""
    configs = get_all_image_generation_configs(db_session)
    return [ImageGenerationConfigView.from_model(config) for config in configs]


@admin_router.get("/config/{image_provider_id}/credentials")
def get_config_credentials(
    image_provider_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
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
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
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

        # Leaving out api_key keeps the current key.
        current_token_id = old_provider.api_token_id if old_provider else None
        api_key = config_update.api_key
        if "api_key" not in config_update.model_fields_set and current_token_id:
            api_key = ExistingApiToken(id=current_token_id)
        if old_provider:
            _validate_llm_provider_change(
                existing_custom_config=old_provider.custom_config,
                new_custom_config=config_update.custom_config,
                uses_saved_key=isinstance(api_key, ExistingApiToken),
            )

        # 3. Build and create new LLM provider
        provider_request = _build_llm_provider_request(
            db_session=db_session,
            image_provider_id=image_provider_id,
            model_name=config_update.model_name,
            provider=config_update.provider,
            api_key=api_key,
            api_base=config_update.api_base,
            api_version=config_update.api_version,
            deployment_name=config_update.deployment_name,
            custom_config=config_update.custom_config,
            current_token_id=current_token_id,
        )

        new_model_config_id = _create_image_gen_llm_provider__no_commit(
            db_session=db_session,
            provider_request=provider_request,
            model_name=config_update.model_name,
            current_token_id=current_token_id,
        )

        # 4. Update the ImageGenerationConfig to point to new model config
        existing_config.model_configuration_id = new_model_config_id

        # 5. Delete old LLM provider (safe now - nothing references it)
        remove_llm_provider(db_session, old_llm_provider_id, commit=False)

        db_session.commit()
        invalidate_provider_listing_cache()
        db_session.refresh(existing_config)
        return ImageGenerationConfigView.from_model(existing_config)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.delete("/config/{image_provider_id}")
def delete_config(
    image_provider_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
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
        remove_llm_provider(db_session, llm_provider_id, commit=False)

        db_session.commit()
        invalidate_provider_listing_cache()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/config/{image_provider_id}/default")
def set_config_as_default(
    image_provider_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
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
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Unset a configuration as the default for image generation."""
    try:
        unset_default_image_generation_config(db_session, image_provider_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
