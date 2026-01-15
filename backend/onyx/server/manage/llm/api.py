import os
from datetime import datetime
from datetime import timezone

import boto3
import httpx
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_chat_accessible_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import fetch_persona_with_groups
from onyx.db.llm import fetch_user_group_ids
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import sync_model_configurations
from onyx.db.llm import update_default_provider
from onyx.db.llm import update_default_vision_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.llm import validate_persona_ids_exist
from onyx.db.models import User
from onyx.db.persona import user_can_access_persona
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import get_llm
from onyx.llm.factory import get_max_input_tokens_from_llm_provider
from onyx.llm.utils import get_bedrock_token_limit
from onyx.llm.utils import get_llm_contextual_cost
from onyx.llm.utils import model_supports_image_input
from onyx.llm.utils import test_llm
from onyx.llm.well_known_providers.auto_update_service import (
    fetch_llm_recommendations_from_github,
)
from onyx.llm.well_known_providers.llm_provider_options import (
    fetch_available_well_known_llms,
)
from onyx.llm.well_known_providers.llm_provider_options import (
    WellKnownLLMProviderDescriptor,
)
from onyx.server.manage.llm.models import BedrockFinalModelResponse
from onyx.server.manage.llm.models import BedrockModelsRequest
from onyx.server.manage.llm.models import LLMCost
from onyx.server.manage.llm.models import LLMProviderDescriptor
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.manage.llm.models import OllamaFinalModelResponse
from onyx.server.manage.llm.models import OllamaModelDetails
from onyx.server.manage.llm.models import OllamaModelsRequest
from onyx.server.manage.llm.models import OpenRouterFinalModelResponse
from onyx.server.manage.llm.models import OpenRouterModelDetails
from onyx.server.manage.llm.models import OpenRouterModelsRequest
from onyx.server.manage.llm.models import TestLLMRequest
from onyx.server.manage.llm.models import VisionProviderResponse
from onyx.server.manage.llm.utils import generate_bedrock_display_name
from onyx.server.manage.llm.utils import generate_ollama_display_name
from onyx.server.manage.llm.utils import infer_vision_support
from onyx.server.manage.llm.utils import is_valid_bedrock_model
from onyx.server.manage.llm.utils import ModelMetadata
from onyx.server.manage.llm.utils import strip_openrouter_vendor_prefix
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/llm")
basic_router = APIRouter(prefix="/llm")


def _mask_provider_api_key(provider_view: LLMProviderView) -> None:
    if provider_view.api_key:
        provider_view.api_key = (
            provider_view.api_key[:4] + "****" + provider_view.api_key[-4:]
        )


@admin_router.get("/built-in/options")
def fetch_llm_options(
    _: User | None = Depends(current_admin_user),
) -> list[WellKnownLLMProviderDescriptor]:
    return fetch_available_well_known_llms()


@admin_router.get("/built-in/options/{provider_name}")
def fetch_llm_provider_options(
    provider_name: str,
    _: User | None = Depends(current_admin_user),
) -> WellKnownLLMProviderDescriptor:
    well_known_llms = fetch_available_well_known_llms()
    for well_known_llm in well_known_llms:
        if well_known_llm.name == provider_name:
            return well_known_llm
    raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")


@admin_router.post("/test")
def test_llm_configuration(
    test_llm_request: TestLLMRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Test LLM configuration settings"""

    # the api key is sanitized if we are testing a provider already in the system

    test_api_key = test_llm_request.api_key
    if test_llm_request.name:
        # NOTE: we are querying by name. we probably should be querying by an invariant id, but
        # as it turns out the name is not editable in the UI and other code also keys off name,
        # so we won't rock the boat just yet.
        existing_provider = fetch_existing_llm_provider(
            name=test_llm_request.name, db_session=db_session
        )
        # if an API key is not provided, use the existing provider's API key
        if existing_provider and not test_llm_request.api_key_changed:
            test_api_key = existing_provider.api_key

    # For this "testing" workflow, we do *not* need the actual `max_input_tokens`.
    # Therefore, instead of performing additional, more complex logic, we just use a dummy value
    max_input_tokens = -1

    llm = get_llm(
        provider=test_llm_request.provider,
        model=test_llm_request.default_model_name,
        api_key=test_api_key,
        api_base=test_llm_request.api_base,
        api_version=test_llm_request.api_version,
        custom_config=test_llm_request.custom_config,
        deployment_name=test_llm_request.deployment_name,
        max_input_tokens=max_input_tokens,
    )

    error_msg = test_llm(llm)

    if error_msg:
        raise HTTPException(status_code=400, detail=error_msg)


@admin_router.post("/test/default")
def test_default_provider(
    _: User | None = Depends(current_admin_user),
) -> None:
    try:
        llm = get_default_llm()
    except ValueError:
        logger.exception("Failed to fetch default LLM Provider")
        raise HTTPException(status_code=400, detail="No LLM Provider setup")

    error = test_llm(llm)
    if error:
        raise HTTPException(status_code=400, detail=str(error))


@admin_router.get("/provider")
def list_llm_providers(
    include_image_gen: bool = Query(False),
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[LLMProviderView]:
    start_time = datetime.now(timezone.utc)
    logger.debug("Starting to fetch LLM providers")

    llm_provider_list: list[LLMProviderView] = []
    for llm_provider_model in fetch_existing_llm_providers(
        db_session, exclude_image_generation_providers=not include_image_gen
    ):
        from_model_start = datetime.now(timezone.utc)
        full_llm_provider = LLMProviderView.from_model(llm_provider_model)
        from_model_end = datetime.now(timezone.utc)
        from_model_duration = (from_model_end - from_model_start).total_seconds()
        logger.debug(
            f"LLMProviderView.from_model took {from_model_duration:.2f} seconds"
        )

        _mask_provider_api_key(full_llm_provider)
        llm_provider_list.append(full_llm_provider)

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    logger.debug(f"Completed fetching LLM providers in {duration:.2f} seconds")

    return llm_provider_list


@admin_router.put("/provider")
def put_llm_provider(
    llm_provider_upsert_request: LLMProviderUpsertRequest,
    is_creation: bool = Query(
        False,
        description="True if updating an existing provider, False if creating a new one",
    ),
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> LLMProviderView:
    # validate request (e.g. if we're intending to create but the name already exists we should throw an error)
    # NOTE: may involve duplicate fetching to Postgres, but we're assuming SQLAlchemy is smart enough to cache
    # the result
    existing_provider = fetch_existing_llm_provider(
        name=llm_provider_upsert_request.name, db_session=db_session
    )
    if existing_provider and is_creation:
        raise HTTPException(
            status_code=400,
            detail=f"LLM Provider with name {llm_provider_upsert_request.name} already exists",
        )
    elif not existing_provider and not is_creation:
        raise HTTPException(
            status_code=400,
            detail=f"LLM Provider with name {llm_provider_upsert_request.name} does not exist",
        )

    persona_ids = llm_provider_upsert_request.personas
    if persona_ids:
        _fetched_persona_ids, missing_personas = validate_persona_ids_exist(
            db_session, persona_ids
        )
        if missing_personas:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid persona IDs: {', '.join(map(str, missing_personas))}",
            )
        # Remove duplicates while preserving order
        seen: set[int] = set()
        deduplicated_personas: list[int] = []
        for persona_id in persona_ids:
            if persona_id not in seen:
                seen.add(persona_id)
                deduplicated_personas.append(persona_id)
        llm_provider_upsert_request.personas = deduplicated_personas

    default_model_found = False

    for model_configuration in llm_provider_upsert_request.model_configurations:
        if model_configuration.name == llm_provider_upsert_request.default_model_name:
            model_configuration.is_visible = True
            default_model_found = True

    if not default_model_found:
        llm_provider_upsert_request.model_configurations.append(
            ModelConfigurationUpsertRequest(
                name=llm_provider_upsert_request.default_model_name, is_visible=True
            )
        )

    # the llm api key is sanitized when returned to clients, so the only time we
    # should get a real key is when it is explicitly changed
    if existing_provider and not llm_provider_upsert_request.api_key_changed:
        llm_provider_upsert_request.api_key = existing_provider.api_key

    # Check if we're transitioning to Auto mode
    transitioning_to_auto_mode = llm_provider_upsert_request.is_auto_mode and (
        not existing_provider or not existing_provider.is_auto_mode
    )

    try:
        result = upsert_llm_provider(
            llm_provider_upsert_request=llm_provider_upsert_request,
            db_session=db_session,
        )

        # If newly enabling Auto mode, sync models immediately from GitHub config
        if transitioning_to_auto_mode:
            from onyx.db.llm import sync_auto_mode_models

            config = fetch_llm_recommendations_from_github()
            if config and llm_provider_upsert_request.provider in config.providers:
                # Refetch the provider to get the updated model
                updated_provider = fetch_existing_llm_provider(
                    name=llm_provider_upsert_request.name, db_session=db_session
                )
                if updated_provider:
                    sync_auto_mode_models(
                        db_session,
                        updated_provider,
                        config,
                    )
                    # Refresh result with synced models
                    result = LLMProviderView.from_model(updated_provider)

        return result
    except ValueError as e:
        logger.exception("Failed to upsert LLM Provider")
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.delete("/provider/{provider_id}")
def delete_llm_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        remove_llm_provider(db_session, provider_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/provider/{provider_id}/default")
def set_provider_as_default(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_default_provider(provider_id=provider_id, db_session=db_session)


@admin_router.post("/provider/{provider_id}/default-vision")
def set_provider_as_default_vision(
    provider_id: int,
    vision_model: str | None = Query(
        None, description="The default vision model to use"
    ),
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_default_vision_provider(
        provider_id=provider_id, vision_model=vision_model, db_session=db_session
    )


@admin_router.get("/auto-config")
def get_auto_config(
    _: User | None = Depends(current_admin_user),
) -> dict:
    """Get the current Auto mode configuration from GitHub.

    Returns the available models and default configurations for each
    supported provider type when using Auto mode.
    """
    config = fetch_llm_recommendations_from_github()
    if not config:
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch configuration from GitHub",
        )
    return config.model_dump()


@admin_router.get("/vision-providers")
def get_vision_capable_providers(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[VisionProviderResponse]:
    """Return a list of LLM providers and their models that support image input"""

    providers = fetch_existing_llm_providers(db_session)
    vision_providers = []

    logger.info("Fetching vision-capable providers")

    for provider in providers:
        vision_models = []

        # Check each model for vision capability
        for model_configuration in provider.model_configurations:
            if model_supports_image_input(model_configuration.name, provider.provider):
                vision_models.append(model_configuration.name)
                logger.debug(
                    f"Vision model found: {provider.provider}/{model_configuration.name}"
                )

        # Only include providers with at least one vision-capable model
        if vision_models:
            provider_view = LLMProviderView.from_model(provider)
            _mask_provider_api_key(provider_view)

            vision_providers.append(
                VisionProviderResponse(
                    **provider_view.model_dump(),
                    vision_models=vision_models,
                )
            )

            logger.info(
                f"Vision provider: {provider.provider} with models: {vision_models}"
            )

    logger.info(f"Found {len(vision_providers)} vision-capable providers")
    return vision_providers


"""Endpoints for all"""


@basic_router.get("/provider")
def list_llm_provider_basics(
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> list[LLMProviderDescriptor]:
    """Get LLM providers accessible to the current user.

    Returns:
    - All public providers (is_public=True) - Always included
    - Restricted providers user can access via their group memberships

    For anonymous users or no_auth mode: returns only public providers
    This ensures backward compatibility while providing better UX for authenticated users.
    """
    start_time = datetime.now(timezone.utc)
    logger.debug("Starting to fetch user-accessible LLM providers")

    all_providers = fetch_existing_llm_providers(db_session)
    user_group_ids = fetch_user_group_ids(db_session, user) if user else set()
    is_admin = user and user.role == UserRole.ADMIN

    accessible_providers = []

    for provider in all_providers:
        # Include all public providers
        if provider.is_public:
            accessible_providers.append(LLMProviderDescriptor.from_model(provider))
            continue

        # Include restricted providers user has access to via groups
        if is_admin:
            # Admins see all providers
            accessible_providers.append(LLMProviderDescriptor.from_model(provider))
        elif provider.groups:
            # User must be in at least one of the provider's groups
            if user_group_ids.intersection({g.id for g in provider.groups}):
                accessible_providers.append(LLMProviderDescriptor.from_model(provider))
        elif not provider.personas:
            # No restrictions = accessible
            accessible_providers.append(LLMProviderDescriptor.from_model(provider))

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    logger.debug(
        f"Completed fetching {len(accessible_providers)} user-accessible providers in {duration:.2f} seconds"
    )

    return accessible_providers


def get_valid_model_names_for_persona(
    persona_id: int,
    user: User | None,
    db_session: Session,
) -> list[str]:
    """Get all valid model names that a user can access for this persona.

    Returns a list of model names (e.g., ["gpt-4o", "claude-3-5-sonnet"]) that are
    available to the user when using this persona, respecting all RBAC restrictions.
    Public providers are always included.
    """
    persona = fetch_persona_with_groups(db_session, persona_id)
    if not persona:
        return []

    is_admin = user is not None and user.role == UserRole.ADMIN
    all_providers = fetch_existing_llm_providers(db_session)
    user_group_ids = set() if is_admin else fetch_user_group_ids(db_session, user)

    valid_models = []
    for llm_provider_model in all_providers:
        # Public providers always included, restricted checked via RBAC
        if can_user_access_llm_provider(
            llm_provider_model, user_group_ids, persona, is_admin=is_admin
        ):
            # Collect all model names from this provider
            for model_config in llm_provider_model.model_configurations:
                if model_config.is_visible:
                    valid_models.append(model_config.name)

    return valid_models


@basic_router.get("/persona/{persona_id}/providers")
def list_llm_providers_for_persona(
    persona_id: int,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> list[LLMProviderDescriptor]:
    """Get LLM providers for a specific persona.

    Returns providers that the user can access when using this persona:
    - All public providers (is_public=True) - ALWAYS included
    - Restricted providers user can access via group/persona restrictions

    This endpoint is used for background fetching of restricted providers
    and should NOT block the UI.
    """
    start_time = datetime.now(timezone.utc)
    logger.debug(f"Starting to fetch LLM providers for persona {persona_id}")

    persona = fetch_persona_with_groups(db_session, persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Verify user has access to this persona
    if not user_can_access_persona(db_session, persona_id, user, get_editable=False):
        raise HTTPException(
            status_code=403,
            detail="You don't have access to this assistant",
        )

    is_admin = user is not None and user.role == UserRole.ADMIN
    all_providers = fetch_existing_llm_providers(db_session)
    user_group_ids = set() if is_admin else fetch_user_group_ids(db_session, user)

    llm_provider_list: list[LLMProviderDescriptor] = []

    for llm_provider_model in all_providers:
        # Use simplified access check - public providers always included
        if can_user_access_llm_provider(
            llm_provider_model, user_group_ids, persona, is_admin=is_admin
        ):
            llm_provider_list.append(
                LLMProviderDescriptor.from_model(llm_provider_model)
            )

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    logger.debug(
        f"Completed fetching {len(llm_provider_list)} LLM providers for persona {persona_id} in {duration:.2f} seconds"
    )

    return llm_provider_list


@admin_router.get("/provider-contextual-cost")
def get_provider_contextual_cost(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[LLMCost]:
    """
    Get the cost of Re-indexing all documents for contextual retrieval.

    See https://docs.litellm.ai/docs/completion/token_usage#5-cost_per_token
    This includes:
    - The cost of invoking the LLM on each chunk-document pair to get
      - the doc_summary
      - the chunk_context
    - The per-token cost of the LLM used to generate the doc_summary and chunk_context
    """
    providers = fetch_existing_llm_providers(db_session)
    costs = []
    for provider in providers:
        for model_configuration in provider.model_configurations:
            llm_provider = LLMProviderView.from_model(provider)
            llm = get_llm(
                provider=provider.provider,
                model=model_configuration.name,
                deployment_name=provider.deployment_name,
                api_key=provider.api_key,
                api_base=provider.api_base,
                api_version=provider.api_version,
                custom_config=provider.custom_config,
                max_input_tokens=get_max_input_tokens_from_llm_provider(
                    llm_provider=llm_provider, model_name=model_configuration.name
                ),
            )
            cost = get_llm_contextual_cost(llm)
            costs.append(
                LLMCost(
                    provider=provider.name,
                    model_name=model_configuration.name,
                    cost=cost,
                )
            )

    return costs


@admin_router.post("/bedrock/available-models")
def get_bedrock_available_models(
    request: BedrockModelsRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[BedrockFinalModelResponse]:
    """Fetch available Bedrock models for a specific region and credentials.

    Returns model IDs with display names from AWS. Prefers inference profiles
    (for cross-region support) over base models when available.
    """
    try:
        # Precedence: bearer → keys → IAM
        if request.aws_bearer_token_bedrock:
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = request.aws_bearer_token_bedrock
            session = boto3.Session(region_name=request.aws_region_name)
        elif request.aws_access_key_id and request.aws_secret_access_key:
            session = boto3.Session(
                aws_access_key_id=request.aws_access_key_id,
                aws_secret_access_key=request.aws_secret_access_key,
                region_name=request.aws_region_name,
            )
        else:
            session = boto3.Session(region_name=request.aws_region_name)

        try:
            bedrock = session.client("bedrock")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to create Bedrock client: {e}. Check AWS credentials and region.",
            )

        # Build model info dict from foundation models (modelId -> metadata)
        model_summaries = bedrock.list_foundation_models().get("modelSummaries", [])
        model_info: dict[str, ModelMetadata] = {}
        available_models: set[str] = set()

        for model in model_summaries:
            model_id = model.get("modelId", "")
            # Skip invalid or non-LLM models (embeddings, image gen, non-streaming)
            if not is_valid_bedrock_model(
                model_id, model.get("responseStreamingSupported", False)
            ):
                continue

            available_models.add(model_id)
            input_modalities = model.get("inputModalities", [])
            model_info[model_id] = {
                "display_name": model.get("modelName", model_id),
                "supports_image_input": "IMAGE" in input_modalities,
            }

        # Get inference profiles (cross-region) - these are preferred over base models
        profile_ids: set[str] = set()
        cross_region_models: set[str] = set()
        try:
            inference_profiles = bedrock.list_inference_profiles(
                typeEquals="SYSTEM_DEFINED"
            ).get("inferenceProfileSummaries", [])
            for profile in inference_profiles:
                if not (profile_id := profile.get("inferenceProfileId")):
                    continue
                # Skip non-LLM inference profiles
                if not is_valid_bedrock_model(profile_id):
                    continue

                profile_ids.add(profile_id)

                # Extract base model ID (everything after first period)
                # e.g., "us.anthropic.claude-3-5-sonnet-..." -> "anthropic.claude-3-5-sonnet-..."
                if "." in profile_id:
                    base_model_id = profile_id.split(".", 1)[1]
                    cross_region_models.add(base_model_id)
                    region = profile_id.split(".")[0]

                    # Copy model info from base model to profile, with region suffix
                    if base_model_id in model_info:
                        base_info = model_info[base_model_id]
                        model_info[profile_id] = {
                            "display_name": f"{base_info['display_name']} ({region})",
                            "supports_image_input": base_info["supports_image_input"],
                        }
                    else:
                        # Base model not in region - infer metadata from profile
                        profile_name = profile.get("inferenceProfileName", "")
                        model_info[profile_id] = {
                            "display_name": (
                                f"{profile_name} ({region})"
                                if profile_name
                                else generate_bedrock_display_name(profile_id)
                            ),
                            # Infer vision support from known vision models
                            "supports_image_input": infer_vision_support(profile_id),
                        }
        except Exception as e:
            logger.warning(f"Couldn't fetch inference profiles for Bedrock: {e}")

        # Prefer profiles: de-dupe available models, then add profile IDs
        candidates = (available_models - cross_region_models) | profile_ids

        # Build response with display names
        results: list[BedrockFinalModelResponse] = []
        for model_id in sorted(candidates, reverse=True):
            info: ModelMetadata | None = model_info.get(model_id)
            display_name = info["display_name"] if info else None

            # Fallback: generate display name from model ID if not available
            if not display_name or display_name == model_id:
                display_name = generate_bedrock_display_name(model_id)

            results.append(
                BedrockFinalModelResponse(
                    name=model_id,
                    display_name=display_name,
                    max_input_tokens=get_bedrock_token_limit(model_id),
                    supports_image_input=(
                        info["supports_image_input"] if info else False
                    ),
                )
            )

        # Unset the environment variable
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

        # Sync new models to DB if provider_name is specified
        if request.provider_name:
            try:
                models_to_sync = [
                    {
                        "name": r.name,
                        "display_name": r.display_name,
                        "max_input_tokens": r.max_input_tokens,
                        "supports_image_input": r.supports_image_input,
                    }
                    for r in results
                ]
                new_count = sync_model_configurations(
                    db_session=db_session,
                    provider_name=request.provider_name,
                    models=models_to_sync,
                )
                if new_count > 0:
                    logger.info(
                        f"Added {new_count} new Bedrock models to provider '{request.provider_name}'"
                    )
            except ValueError as e:
                logger.warning(f"Failed to sync Bedrock models to DB: {e}")

        return results

    except (ClientError, NoCredentialsError, BotoCoreError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect to AWS Bedrock: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error fetching Bedrock models: {e}",
        )


def _get_ollama_available_model_names(api_base: str) -> set[str]:
    """Fetch available model names from Ollama server."""
    tags_url = f"{api_base}/api/tags"
    try:
        response = httpx.get(tags_url, timeout=5.0)
        response.raise_for_status()
        response_json = response.json()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch Ollama models: {e}",
        )

    models = response_json.get("models", [])
    return {model.get("name") for model in models if model.get("name")}


@admin_router.post("/ollama/available-models")
def get_ollama_available_models(
    request: OllamaModelsRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[OllamaFinalModelResponse]:
    """Fetch the list of available models from an Ollama server."""

    cleaned_api_base = request.api_base.strip().rstrip("/")
    if not cleaned_api_base:
        raise HTTPException(
            status_code=400,
            detail="API base URL is required to fetch Ollama models.",
        )

    # NOTE: most people run Ollama locally, so we don't disallow internal URLs
    # the only way this could be used for SSRF is if there's another endpoint that
    # is not protected + exposes sensitive information on the `/api/tags` endpoint
    # with the same response format
    model_names = _get_ollama_available_model_names(cleaned_api_base)
    if not model_names:
        raise HTTPException(
            status_code=400,
            detail="No models found from your Ollama server",
        )

    all_models_with_context_size_and_vision: list[OllamaFinalModelResponse] = []
    show_url = f"{cleaned_api_base}/api/show"

    for model_name in model_names:
        context_limit: int | None = None
        supports_image_input: bool | None = None
        try:
            show_response = httpx.post(
                show_url,
                json={"model": model_name},
                timeout=5.0,
            )
            show_response.raise_for_status()
            show_response_json = show_response.json()

            # Parse the response into the expected format
            ollama_model_details = OllamaModelDetails.model_validate(show_response_json)

            # Check if this model supports completion/chat
            if not ollama_model_details.supports_completion():
                continue

            # Optimistically access. Context limit is stored as "model_architecture.context" = int
            architecture = ollama_model_details.model_info.get(
                "general.architecture", ""
            )
            context_limit = ollama_model_details.model_info.get(
                architecture + ".context_length", None
            )
            supports_image_input = ollama_model_details.supports_image_input()
        except ValidationError as e:
            logger.warning(
                "Invalid model details from Ollama server",
                extra={"model": model_name, "validation_error": str(e)},
            )
        except Exception as e:
            logger.warning(
                "Failed to fetch Ollama model details",
                extra={"model": model_name, "error": str(e)},
            )

        # Note: context_limit may be None if Ollama API doesn't provide it.
        # The runtime will use LiteLLM fallback logic to determine max tokens.
        all_models_with_context_size_and_vision.append(
            OllamaFinalModelResponse(
                name=model_name,
                display_name=generate_ollama_display_name(model_name),
                max_input_tokens=context_limit,
                supports_image_input=supports_image_input or False,
            )
        )

    # Sync new models to DB if provider_name is specified
    if request.provider_name:
        try:
            models_to_sync = [
                {
                    "name": r.name,
                    "display_name": r.display_name,
                    "max_input_tokens": r.max_input_tokens,
                    "supports_image_input": r.supports_image_input,
                }
                for r in all_models_with_context_size_and_vision
            ]
            new_count = sync_model_configurations(
                db_session=db_session,
                provider_name=request.provider_name,
                models=models_to_sync,
            )
            if new_count > 0:
                logger.info(
                    f"Added {new_count} new Ollama models to provider '{request.provider_name}'"
                )
        except ValueError as e:
            logger.warning(f"Failed to sync Ollama models to DB: {e}")

    return all_models_with_context_size_and_vision


def _get_openrouter_models_response(api_base: str, api_key: str) -> dict:
    """Perform GET to OpenRouter /models and return parsed JSON."""
    cleaned_api_base = api_base.strip().rstrip("/")
    url = f"{cleaned_api_base}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        # Optional headers recommended by OpenRouter for attribution
        "HTTP-Referer": "https://onyx.app",
        "X-Title": "Onyx",
    }
    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch OpenRouter models: {e}",
        )


@admin_router.post("/openrouter/available-models")
def get_openrouter_available_models(
    request: OpenRouterModelsRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[OpenRouterFinalModelResponse]:
    """Fetch available models from OpenRouter `/models` endpoint.

    Parses id, name (display), context_length, and architecture.input_modalities.
    """

    response_json = _get_openrouter_models_response(
        api_base=request.api_base, api_key=request.api_key
    )

    data = response_json.get("data", [])
    if not isinstance(data, list) or len(data) == 0:
        raise HTTPException(
            status_code=400,
            detail="No models found from your OpenRouter endpoint",
        )

    results: list[OpenRouterFinalModelResponse] = []
    for item in data:
        try:
            model_details = OpenRouterModelDetails.model_validate(item)

            # NOTE: This should be removed if we ever support dynamically fetching embedding models.
            if model_details.is_embedding_model:
                continue

            # Strip vendor prefix since we group by vendor (e.g., "Microsoft: Phi 4" → "Phi 4")
            display_name = strip_openrouter_vendor_prefix(
                model_details.display_name, model_details.id
            )

            # Treat context_length of 0 as unknown (None)
            context_length = model_details.context_length or None

            results.append(
                OpenRouterFinalModelResponse(
                    name=model_details.id,
                    display_name=display_name,
                    max_input_tokens=context_length,
                    supports_image_input=model_details.supports_image_input,
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to parse OpenRouter model entry",
                extra={"error": str(e), "item": str(item)[:1000]},
            )

    if not results:
        raise HTTPException(
            status_code=400, detail="No compatible models found from OpenRouter"
        )

    sorted_results = sorted(results, key=lambda m: m.name.lower())

    # Sync new models to DB if provider_name is specified
    if request.provider_name:
        try:
            models_to_sync = [
                {
                    "name": r.name,
                    "display_name": r.display_name,
                    "max_input_tokens": r.max_input_tokens,
                    "supports_image_input": r.supports_image_input,
                }
                for r in sorted_results
            ]
            new_count = sync_model_configurations(
                db_session=db_session,
                provider_name=request.provider_name,
                models=models_to_sync,
            )
            if new_count > 0:
                logger.info(
                    f"Added {new_count} new OpenRouter models to provider '{request.provider_name}'"
                )
        except ValueError as e:
            logger.warning(f"Failed to sync OpenRouter models to DB: {e}")

    return sorted_results
