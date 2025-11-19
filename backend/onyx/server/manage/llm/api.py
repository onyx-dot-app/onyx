import os
from collections.abc import Callable
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

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_chat_accessible_user
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.db.engine.sql_engine import get_session
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import fetch_existing_llm_providers_for_user
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import update_default_vision_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import User
from onyx.llm.factory import get_default_llms
from onyx.llm.factory import get_llm
from onyx.llm.factory import get_max_input_tokens_from_llm_provider
from onyx.llm.llm_provider_options import fetch_available_well_known_llms
from onyx.llm.llm_provider_options import get_bedrock_model_names
from onyx.llm.llm_provider_options import WellKnownLLMProviderDescriptor
from onyx.llm.utils import get_llm_contextual_cost
from onyx.llm.utils import litellm_exception_to_error_msg
from onyx.llm.utils import model_supports_image_input
from onyx.llm.utils import test_llm
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
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/llm")
basic_router = APIRouter(prefix="/llm")


@admin_router.get("/built-in/options")
def fetch_llm_options(
    _: User | None = Depends(current_admin_user),
) -> list[WellKnownLLMProviderDescriptor]:
    return fetch_available_well_known_llms()


@admin_router.post("/test")
def test_llm_configuration(
    test_llm_request: TestLLMRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Test regular llm and fast llm settings"""

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

    functions_with_args: list[tuple[Callable, tuple]] = [(test_llm, (llm,))]
    if (
        test_llm_request.fast_default_model_name
        and test_llm_request.fast_default_model_name
        != test_llm_request.default_model_name
    ):
        fast_llm = get_llm(
            provider=test_llm_request.provider,
            model=test_llm_request.fast_default_model_name,
            api_key=test_api_key,
            api_base=test_llm_request.api_base,
            api_version=test_llm_request.api_version,
            custom_config=test_llm_request.custom_config,
            deployment_name=test_llm_request.deployment_name,
            max_input_tokens=max_input_tokens,
        )
        functions_with_args.append((test_llm, (fast_llm,)))

    parallel_results = run_functions_tuples_in_parallel(
        functions_with_args, allow_failures=False
    )
    error = parallel_results[0] or (
        parallel_results[1] if len(parallel_results) > 1 else None
    )

    if error:
        client_error_msg = litellm_exception_to_error_msg(
            error, llm, fallback_to_error_msg=True
        )
        raise HTTPException(status_code=400, detail=client_error_msg)


@admin_router.post("/test/default")
def test_default_provider(
    _: User | None = Depends(current_admin_user),
) -> None:
    try:
        llm, fast_llm = get_default_llms()
    except ValueError:
        logger.exception("Failed to fetch default LLM Provider")
        raise HTTPException(status_code=400, detail="No LLM Provider setup")

    functions_with_args: list[tuple[Callable, tuple]] = [
        (test_llm, (llm,)),
        (test_llm, (fast_llm,)),
    ]
    parallel_results = run_functions_tuples_in_parallel(
        functions_with_args, allow_failures=False
    )
    error = parallel_results[0] or (
        parallel_results[1] if len(parallel_results) > 1 else None
    )
    if error:
        raise HTTPException(status_code=400, detail=error)


@admin_router.get("/provider")
def list_llm_providers(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[LLMProviderView]:
    start_time = datetime.now(timezone.utc)
    logger.debug("Starting to fetch LLM providers")

    llm_provider_list: list[LLMProviderView] = []
    for llm_provider_model in fetch_existing_llm_providers(db_session):
        from_model_start = datetime.now(timezone.utc)
        full_llm_provider = LLMProviderView.from_model(llm_provider_model)
        from_model_end = datetime.now(timezone.utc)
        from_model_duration = (from_model_end - from_model_start).total_seconds()
        logger.debug(
            f"LLMProviderView.from_model took {from_model_duration:.2f} seconds"
        )

        if full_llm_provider.api_key:
            full_llm_provider.api_key = (
                full_llm_provider.api_key[:4] + "****" + full_llm_provider.api_key[-4:]
            )
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

    default_model_found = False
    default_fast_model_found = False

    for model_configuration in llm_provider_upsert_request.model_configurations:
        if model_configuration.name == llm_provider_upsert_request.default_model_name:
            model_configuration.is_visible = True
            default_model_found = True
        if (
            llm_provider_upsert_request.fast_default_model_name
            and llm_provider_upsert_request.fast_default_model_name
            == model_configuration.name
        ):
            model_configuration.is_visible = True
            default_fast_model_found = True

    default_inserts = set()
    if not default_model_found:
        default_inserts.add(llm_provider_upsert_request.default_model_name)

    if (
        llm_provider_upsert_request.fast_default_model_name
        and not default_fast_model_found
    ):
        default_inserts.add(llm_provider_upsert_request.fast_default_model_name)

    llm_provider_upsert_request.model_configurations.extend(
        ModelConfigurationUpsertRequest(name=name, is_visible=True)
        for name in default_inserts
    )

    # the llm api key is sanitized when returned to clients, so the only time we
    # should get a real key is when it is explicitly changed
    if existing_provider and not llm_provider_upsert_request.api_key_changed:
        llm_provider_upsert_request.api_key = existing_provider.api_key

    try:
        return upsert_llm_provider(
            llm_provider_upsert_request=llm_provider_upsert_request,
            db_session=db_session,
        )
    except ValueError as e:
        logger.exception("Failed to upsert LLM Provider")
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.delete("/provider/{provider_id}")
def delete_llm_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    remove_llm_provider(db_session, provider_id)


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
            provider_dict = LLMProviderView.from_model(provider).model_dump()
            provider_dict["vision_models"] = vision_models
            logger.info(
                f"Vision provider: {provider.provider} with models: {vision_models}"
            )
            vision_providers.append(VisionProviderResponse(**provider_dict))

    logger.info(f"Found {len(vision_providers)} vision-capable providers")
    return vision_providers


"""Endpoints for all"""


@basic_router.get("/provider")
def list_llm_provider_basics(
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> list[LLMProviderDescriptor]:
    start_time = datetime.now(timezone.utc)
    logger.debug("Starting to fetch basic LLM providers for user")

    llm_provider_list: list[LLMProviderDescriptor] = []
    for llm_provider_model in fetch_existing_llm_providers_for_user(db_session, user):
        from_model_start = datetime.now(timezone.utc)
        full_llm_provider = LLMProviderDescriptor.from_model(llm_provider_model)
        from_model_end = datetime.now(timezone.utc)
        from_model_duration = (from_model_end - from_model_start).total_seconds()
        logger.debug(
            f"LLMProviderView.from_model took {from_model_duration:.2f} seconds"
        )
        llm_provider_list.append(full_llm_provider)

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    logger.debug(f"Completed fetching basic LLM providers in {duration:.2f} seconds")

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
) -> list[str]:
    """Fetch available Bedrock models for a specific region and credentials"""
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

        # Available Bedrock models: text-only, streaming supported
        model_summaries = bedrock.list_foundation_models().get("modelSummaries", [])
        available_models = {
            model.get("modelId", "")
            for model in model_summaries
            if model.get("modelId")
            and "embed" not in model.get("modelId", "").lower()
            and model.get("responseStreamingSupported", False)
        }

        # Available inference profiles. Invoking these allows cross-region inference (preferred over base models).
        profile_ids: set[str] = set()
        cross_region_models: set[str] = set()
        try:
            inference_profiles = bedrock.list_inference_profiles(
                typeEquals="SYSTEM_DEFINED"
            ).get("inferenceProfileSummaries", [])
            for profile in inference_profiles:
                if profile_id := profile.get("inferenceProfileId"):
                    profile_ids.add(profile_id)

                    # The model id is everything after the first period in the profile id
                    if "." in profile_id:
                        model_id = profile_id.split(".", 1)[1]
                        cross_region_models.add(model_id)
        except Exception as e:
            # Cross-region inference isn't guaranteed; ignore failures here.
            logger.warning(f"Couldn't fetch inference profiles for Bedrock: {e}")

        # Prefer profiles: de-dupe available models, then add profile IDs
        candidates = (available_models - cross_region_models) | profile_ids

        # Keep only models we support (compatibility with litellm)
        filtered = sorted(
            [model for model in candidates if model in get_bedrock_model_names()],
            reverse=True,
        )

        # Unset the environment variable, even though it is set again in DefaultMultiLLM init
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

        return filtered

    except (ClientError, NoCredentialsError, BotoCoreError) as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to connect to AWS Bedrock: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Unexpected error fetching Bedrock models: {e}"
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
) -> list[OllamaFinalModelResponse]:
    """Fetch the list of available models from an Ollama server."""

    cleaned_api_base = request.api_base.strip().rstrip("/")
    if not cleaned_api_base:
        raise HTTPException(
            status_code=400, detail="API base URL is required to fetch Ollama models."
        )

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

        # If we fail at any point attempting to extract context limit,
        # still allow this model to be used with a fallback max context size
        if not context_limit:
            context_limit = GEN_AI_MODEL_FALLBACK_MAX_TOKENS

        if not supports_image_input:
            supports_image_input = False

        all_models_with_context_size_and_vision.append(
            OllamaFinalModelResponse(
                name=model_name,
                max_input_tokens=context_limit,
                supports_image_input=supports_image_input,
            )
        )

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
) -> list[OpenRouterFinalModelResponse]:
    """Fetch available models from OpenRouter `/models` endpoint.

    Parses id, context_length, and architecture.input_modalities to infer vision support.
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

            results.append(
                OpenRouterFinalModelResponse(
                    name=model_details.id,
                    max_input_tokens=model_details.context_length,
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

    return sorted(results, key=lambda m: m.name.lower())
