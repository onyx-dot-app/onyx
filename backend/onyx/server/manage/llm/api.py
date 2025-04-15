from collections.abc import Callable
from datetime import datetime
from datetime import timezone

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_chat_accessible_user
from onyx.db.engine import get_session
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
from onyx.llm.llm_provider_options import fetch_available_well_known_llms
from onyx.llm.llm_provider_options import WellKnownLLMProviderDescriptor
from onyx.llm.utils import get_llm_contextual_cost
from onyx.llm.utils import litellm_exception_to_error_msg
from onyx.llm.utils import model_supports_image_input
from onyx.llm.utils import test_llm
from onyx.server.manage.llm.models import LLMCost
from onyx.server.manage.llm.models import LLMProviderDescriptor
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
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
            test_llm_request.name, db_session
        )
        if existing_provider:
            test_api_key = existing_provider.api_key

    llm = get_llm(
        provider=test_llm_request.provider,
        model=test_llm_request.default_model_name,
        api_key=test_api_key,
        api_base=test_llm_request.api_base,
        api_version=test_llm_request.api_version,
        custom_config=test_llm_request.custom_config,
        deployment_name=test_llm_request.deployment_name,
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
    llm_provider: LLMProviderUpsertRequest,
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
    existing_provider = fetch_existing_llm_provider(llm_provider.name, db_session)
    if existing_provider and is_creation:
        raise HTTPException(
            status_code=400,
            detail=f"LLM Provider with name {llm_provider.name} already exists",
        )

    if llm_provider.display_model_names is not None:
        # Ensure default_model_name and fast_default_model_name are in display_model_names
        # This is necessary for custom models and Bedrock/Azure models
        if llm_provider.default_model_name not in llm_provider.display_model_names:
            llm_provider.display_model_names.append(llm_provider.default_model_name)

        if (
            llm_provider.fast_default_model_name
            and llm_provider.fast_default_model_name
            not in llm_provider.display_model_names
        ):
            llm_provider.display_model_names.append(
                llm_provider.fast_default_model_name
            )

    # the llm api key is sanitized when returned to clients, so the only time we
    # should get a real key is when it is explicitly changed
    if existing_provider and not llm_provider.api_key_changed:
        llm_provider.api_key = existing_provider.api_key

    try:
        return upsert_llm_provider(
            llm_provider=llm_provider,
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

        # Check model names in priority order
        model_names_to_check = []
        if provider.model_names:
            model_names_to_check = provider.model_names
        elif provider.display_model_names:
            model_names_to_check = provider.display_model_names
        elif provider.default_model_name:
            model_names_to_check = [provider.default_model_name]

        # Check each model for vision capability
        for model_name in model_names_to_check:
            if model_supports_image_input(model_name, provider.provider):
                vision_models.append(model_name)
                logger.debug(f"Vision model found: {provider.provider}/{model_name}")

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


@basic_router.get("/human_readable_model_names_map")
def get_human_readable_model_names_map(
    _user: User | None = Depends(current_admin_user),
    _db_session: Session = Depends(get_session),
) -> dict[str, str]:
    return {
        # OpenAI models
        "o1-2025-12-17": "o1 (December 2025)",
        "o3-mini": "o3 Mini",
        "o1-mini": "o1 Mini",
        "o1-preview": "o1 Preview",
        "o1": "o1",
        "gpt-4": "GPT 4",
        "gpt-4o": "GPT 4o",
        "gpt-4o-2024-08-06": "GPT 4o (Structured Outputs)",
        "gpt-4o-mini": "GPT 4o Mini",
        "gpt-4-0314": "GPT 4 (March 2023)",
        "gpt-4-0613": "GPT 4 (June 2023)",
        "gpt-4-32k-0314": "GPT 4 32k (March 2023)",
        "gpt-4-turbo": "GPT 4 Turbo",
        "gpt-4-turbo-preview": "GPT 4 Turbo (Preview)",
        "gpt-4-1106-preview": "GPT 4 Turbo (November 2023)",
        "gpt-4-vision-preview": "GPT 4 Vision (Preview)",
        "gpt-3.5-turbo": "GPT 3.5 Turbo",
        "gpt-3.5-turbo-0125": "GPT 3.5 Turbo (January 2024)",
        "gpt-3.5-turbo-1106": "GPT 3.5 Turbo (November 2023)",
        "gpt-3.5-turbo-16k": "GPT 3.5 Turbo 16k",
        "gpt-3.5-turbo-0613": "GPT 3.5 Turbo (June 2023)",
        "gpt-3.5-turbo-16k-0613": "GPT 3.5 Turbo 16k (June 2023)",
        "gpt-3.5-turbo-0301": "GPT 3.5 Turbo (March 2023)",
        # Amazon models
        "amazon.nova-micro@v1": "Amazon Nova Micro",
        "amazon.nova-lite@v1": "Amazon Nova Lite",
        "amazon.nova-pro@v1": "Amazon Nova Pro",
        # Meta models
        "llama-3.2-90b-vision-instruct": "Llama 3.2 90B",
        "llama-3.2-11b-vision-instruct": "Llama 3.2 11B",
        "llama-3.3-70b-instruct": "Llama 3.3 70B",
        # Microsoft models
        "phi-3.5-mini-instruct": "Phi 3.5 Mini",
        "phi-3.5-moe-instruct": "Phi 3.5 MoE",
        "phi-3.5-vision-instruct": "Phi 3.5 Vision",
        "phi-4": "Phi 4",
        # Deepseek Models
        "deepseek-r1": "DeepSeek R1",
        # Anthropic models
        "claude-3-opus-20240229": "Claude 3 Opus",
        "claude-3-sonnet-20240229": "Claude 3 Sonnet",
        "claude-3-haiku-20240307": "Claude 3 Haiku",
        "claude-2.1": "Claude 2.1",
        "claude-2.0": "Claude 2.0",
        "claude-instant-1.2": "Claude Instant 1.2",
        "claude-3-5-sonnet-20240620": "Claude 3.5 Sonnet (June 2024)",
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
        "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet",
        "claude-3-5-sonnet-v2@20241022": "Claude 3.5 Sonnet",
        "claude-3.5-sonnet-v2@20241022": "Claude 3.5 Sonnet",
        "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
        "claude-3-5-haiku@20241022": "Claude 3.5 Haiku",
        "claude-3.5-haiku@20241022": "Claude 3.5 Haiku",
        "claude-3.7-sonnet@202502019": "Claude 3.7 Sonnet",
        "claude-3-7-sonnet-202502019": "Claude 3.7 Sonnet",
        # Google Models
        # 2.5 pro models
        "gemini-2.5-pro-exp-03-25": "Gemini 2.5 Pro (Experimental March 25th)",
        # 2.0 flash lite models
        "gemini-2.0-flash-lite": "Gemini 2.0 Flash Lite",
        "gemini-2.0-flash-lite-001": "Gemini 2.0 Flash Lite (v1)",
        # "gemini-2.0-flash-lite-preview-02-05": "Gemini 2.0 Flash Lite (Prv)",
        # "gemini-2.0-pro-exp-02-05": "Gemini 2.0 Pro (Exp)",
        # 2.0 flash models
        "gemini-2.0-flash": "Gemini 2.0 Flash",
        "gemini-2.0-flash-001": "Gemini 2.0 Flash (v1)",
        "gemini-2.0-flash-exp": "Gemini 2.0 Flash (Experimental)",
        # "gemini-2.0-flash-thinking-exp-01-02":
        #   "Gemini 2.0 Flash Thinking (Experimental January 2nd)",
        # "gemini-2.0-flash-thinking-exp-01-21":
        #   "Gemini 2.0 Flash Thinking (Experimental January 21st)",
        # 1.5 pro models
        "gemini-1.5-pro": "Gemini 1.5 Pro",
        "gemini-1.5-pro-latest": "Gemini 1.5 Pro (Latest)",
        "gemini-1.5-pro-001": "Gemini 1.5 Pro (v1)",
        "gemini-1.5-pro-002": "Gemini 1.5 Pro (v2)",
        # 1.5 flash models
        "gemini-1.5-flash": "Gemini 1.5 Flash",
        "gemini-1.5-flash-latest": "Gemini 1.5 Flash (Latest)",
        "gemini-1.5-flash-002": "Gemini 1.5 Flash (v2)",
        "gemini-1.5-flash-001": "Gemini 1.5 Flash (v1)",
        # Mistral Models
        "mistral-large-2411": "Mistral Large 24.11",
        "mistral-large@2411": "Mistral Large 24.11",
        "ministral-3b": "Ministral 3B",
        # Bedrock models
        "meta.llama3-1-70b-instruct-v1:0": "Llama 3.1 70B",
        "meta.llama3-1-8b-instruct-v1:0": "Llama 3.1 8B",
        "meta.llama3-70b-instruct-v1:0": "Llama 3 70B",
        "meta.llama3-2-1b-instruct-v1:0": "Llama 3.2 1B",
        "meta.llama3-2-3b-instruct-v1:0": "Llama 3.2 3B",
        "meta.llama3-2-11b-instruct-v1:0": "Llama 3.2 11B",
        "meta.llama3-2-90b-instruct-v1:0": "Llama 3.2 90B",
        "meta.llama3-8b-instruct-v1:0": "Llama 3 8B",
        "meta.llama2-70b-chat-v1": "Llama 2 70B",
        "meta.llama2-13b-chat-v1": "Llama 2 13B",
        "cohere.command-r-v1:0": "Command R",
        "cohere.command-r-plus-v1:0": "Command R Plus",
        "cohere.command-light-text-v14": "Command Light Text",
        "cohere.command-text-v14": "Command Text",
        "anthropic.claude-instant-v1": "Claude Instant",
        "anthropic.claude-v2:1": "Claude v2.1",
        "anthropic.claude-v2": "Claude v2",
        "anthropic.claude-v1": "Claude v1",
        "anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet",
        "anthropic.claude-3-opus-20240229-v1:0": "Claude 3 Opus",
        "anthropic.claude-3-haiku-20240307-v1:0": "Claude 3 Haiku",
        "anthropic.claude-3-5-sonnet-20240620-v1:0": "Claude 3.5 Sonnet",
        "anthropic.claude-3-5-sonnet-20241022-v2:0": "Claude 3.5 Sonnet (New)",
        "anthropic.claude-3-sonnet-20240229-v1:0": "Claude 3 Sonnet",
        "mistral.mistral-large-2402-v1:0": "Mistral Large",
        "mistral.mixtral-8x7b-instruct-v0:1": "Mixtral 8x7B Instruct",
        "mistral.mistral-7b-instruct-v0:2": "Mistral 7B Instruct",
        "amazon.titan-text-express-v1": "Titan Text Express",
        "amazon.titan-text-lite-v1": "Titan Text Lite",
        "ai21.jamba-instruct-v1:0": "Jamba Instruct",
        "ai21.j2-ultra-v1": "J2 Ultra",
        "ai21.j2-mid-v1": "J2 Mid",
    }


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
        for model_name in provider.display_model_names or provider.model_names or []:
            llm = get_llm(
                provider=provider.provider,
                model=model_name,
                deployment_name=provider.deployment_name,
                api_key=provider.api_key,
                api_base=provider.api_base,
                api_version=provider.api_version,
                custom_config=provider.custom_config,
            )
            cost = get_llm_contextual_cost(llm)
            costs.append(
                LLMCost(provider=provider.name, model_name=model_name, cost=cost)
            )
    return costs
