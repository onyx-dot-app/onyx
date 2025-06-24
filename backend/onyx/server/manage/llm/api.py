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
from onyx.llm.llm_provider_options import WellKnownLLMProviderDescriptor
from onyx.llm.utils import get_llm_contextual_cost
from onyx.llm.utils import litellm_exception_to_error_msg
from onyx.llm.utils import model_supports_image_input
from onyx.llm.utils import test_llm
from onyx.server.manage.llm.models import LLMCost
from onyx.server.manage.llm.models import LLMProviderDescriptor
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
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
