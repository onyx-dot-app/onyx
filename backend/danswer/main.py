import time
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from typing import cast

import uvicorn
from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx_oauth.clients.google import GoogleOAuth2
from sqlalchemy.orm import Session

from danswer import __version__
from danswer.auth.schemas import UserCreate
from danswer.auth.schemas import UserRead
from danswer.auth.schemas import UserUpdate
from danswer.auth.users import auth_backend
from danswer.auth.users import fastapi_users
from danswer.chat.load_yamls import load_chat_yamls
from danswer.configs.app_configs import APP_API_PREFIX
from danswer.configs.app_configs import APP_HOST
from danswer.configs.app_configs import APP_PORT
from danswer.configs.app_configs import AUTH_TYPE
from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from danswer.configs.app_configs import LOG_ENDPOINT_LATENCY
from danswer.configs.app_configs import OAUTH_CLIENT_ID
from danswer.configs.app_configs import OAUTH_CLIENT_SECRET
from danswer.configs.app_configs import USER_AUTH_SECRET
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.configs.constants import AuthType
from danswer.configs.constants import KV_REINDEX_KEY
from danswer.configs.constants import KV_SEARCH_SETTINGS
from danswer.configs.constants import POSTGRES_WEB_APP_NAME
from danswer.configs.model_configs import FAST_GEN_AI_MODEL_VERSION
from danswer.configs.model_configs import GEN_AI_API_KEY
from danswer.configs.model_configs import GEN_AI_MODEL_VERSION
from danswer.db.connector import check_connectors_exist
from danswer.db.connector import create_initial_default_connector
from danswer.db.connector_credential_pair import associate_default_cc_pair
from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.connector_credential_pair import resync_cc_pair
from danswer.db.credentials import create_initial_public_credential
from danswer.db.document import check_docs_exist
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.engine import init_sqlalchemy_engine
from danswer.db.engine import warm_up_connections
from danswer.db.index_attempt import cancel_indexing_attempts_past_model
from danswer.db.index_attempt import expire_index_attempts
from danswer.db.llm import fetch_default_provider
from danswer.db.llm import update_default_provider
from danswer.db.llm import upsert_llm_provider
from danswer.db.persona import delete_old_default_personas
from danswer.db.search_settings import get_current_search_settings
from danswer.db.search_settings import get_secondary_search_settings
from danswer.db.search_settings import update_current_search_settings
from danswer.db.search_settings import update_secondary_search_settings
from danswer.db.standard_answer import create_initial_default_standard_answer_category
from danswer.db.swap_index import check_index_swap
from danswer.document_index.factory import get_default_document_index
from danswer.document_index.interfaces import DocumentIndex
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.indexing.models import IndexingSetting
from danswer.natural_language_processing.search_nlp_models import EmbeddingModel
from danswer.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from danswer.natural_language_processing.search_nlp_models import warm_up_cross_encoder
from danswer.search.models import SavedSearchSettings
from danswer.search.retrieval.search_runner import download_nltk_data
from danswer.server.auth_check import check_router_auth
from danswer.server.danswer_api.ingestion import router as danswer_api_router
from danswer.server.documents.cc_pair import router as cc_pair_router
from danswer.server.documents.connector import router as connector_router
from danswer.server.documents.credential import router as credential_router
from danswer.server.documents.document import router as document_router
from danswer.server.documents.indexing import router as indexing_router
from danswer.server.features.document_set.api import router as document_set_router
from danswer.server.features.folder.api import router as folder_router
from danswer.server.features.input_prompt.api import (
    admin_router as admin_input_prompt_router,
)
from danswer.server.features.input_prompt.api import basic_router as input_prompt_router
from danswer.server.features.persona.api import admin_router as admin_persona_router
from danswer.server.features.persona.api import basic_router as persona_router
from danswer.server.features.prompt.api import basic_router as prompt_router
from danswer.server.features.tool.api import admin_router as admin_tool_router
from danswer.server.features.tool.api import router as tool_router
from danswer.server.gpts.api import router as gpts_router
from danswer.server.manage.administrative import router as admin_router
from danswer.server.manage.embedding.api import admin_router as embedding_admin_router
from danswer.server.manage.embedding.api import basic_router as embedding_router
from danswer.server.manage.get_state import router as state_router
from danswer.server.manage.llm.api import admin_router as llm_admin_router
from danswer.server.manage.llm.api import basic_router as llm_router
from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from danswer.server.manage.search_settings import router as search_settings_router
from danswer.server.manage.slack_bot import router as slack_bot_management_router
from danswer.server.manage.users import router as user_router
from danswer.server.middleware.latency_logging import add_latency_logging_middleware
from danswer.server.query_and_chat.chat_backend import router as chat_router
from danswer.server.query_and_chat.query_backend import (
    admin_router as admin_query_router,
)
from danswer.server.query_and_chat.query_backend import basic_router as query_router
from danswer.server.settings.api import admin_router as settings_admin_router
from danswer.server.settings.api import basic_router as settings_router
from danswer.server.token_rate_limits.api import (
    router as token_rate_limit_settings_router,
)
from danswer.tools.built_in_tools import auto_add_search_tool_to_personas
from danswer.tools.built_in_tools import load_builtin_tools
from danswer.tools.built_in_tools import refresh_built_in_tools_cache
from danswer.utils.gpu_utils import gpu_status_request
from danswer.utils.logger import setup_logger
from danswer.utils.telemetry import get_or_generate_uuid
from danswer.utils.telemetry import optional_telemetry
from danswer.utils.telemetry import RecordType
from danswer.utils.variable_functionality import fetch_versioned_implementation
from danswer.utils.variable_functionality import global_version
from danswer.utils.variable_functionality import set_is_ee_based_on_env_variable
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT


from danswer.server.eea_config.eea_config_backend import router as eea_config_router

logger = setup_logger()


def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        logger.error(
            f"Unexpected exception type in validation_exception_handler - {type(exc)}"
        )
        raise exc

    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    logger.exception(f"{request}: {exc_str}")
    content = {"status_code": 422, "message": exc_str, "data": None}
    return JSONResponse(content=content, status_code=422)


def value_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ValueError):
        logger.error(f"Unexpected exception type in value_error_handler - {type(exc)}")
        raise exc

    try:
        raise (exc)
    except Exception:
        # log stacktrace
        logger.exception("ValueError")
    return JSONResponse(
        status_code=400,
        content={"message": str(exc)},
    )


def include_router_with_global_prefix_prepended(
    application: FastAPI, router: APIRouter, **kwargs: Any
) -> None:
    """Adds the global prefix to all routes in the router."""
    processed_global_prefix = f"/{APP_API_PREFIX.strip('/')}" if APP_API_PREFIX else ""

    passed_in_prefix = cast(str | None, kwargs.get("prefix"))
    if passed_in_prefix:
        final_prefix = f"{processed_global_prefix}/{passed_in_prefix.strip('/')}"
    else:
        final_prefix = f"{processed_global_prefix}"
    final_kwargs: dict[str, Any] = {
        **kwargs,
        "prefix": final_prefix,
    }

    application.include_router(router, **final_kwargs)


def setup_postgres(db_session: Session) -> None:
    logger.notice("Verifying default connector/credential exist.")
    create_initial_public_credential(db_session)
    create_initial_default_connector(db_session)
    associate_default_cc_pair(db_session)

    logger.notice("Verifying default standard answer category exists.")
    create_initial_default_standard_answer_category(db_session)

    logger.notice("Loading default Prompts and Personas")
    delete_old_default_personas(db_session)
    load_chat_yamls()

    logger.notice("Loading built-in tools")
    load_builtin_tools(db_session)
    refresh_built_in_tools_cache(db_session)
    auto_add_search_tool_to_personas(db_session)

    if GEN_AI_API_KEY and fetch_default_provider(db_session) is None:
        # Only for dev flows
        logger.notice("Setting up default OpenAI LLM for dev.")
        llm_model = GEN_AI_MODEL_VERSION or "gpt-4o-mini"
        fast_model = FAST_GEN_AI_MODEL_VERSION or "gpt-4o-mini"
        model_req = LLMProviderUpsertRequest(
            name="DevEnvPresetOpenAI",
            provider="openai",
            api_key=GEN_AI_API_KEY,
            api_base=None,
            api_version=None,
            custom_config=None,
            default_model_name=llm_model,
            fast_default_model_name=fast_model,
            is_public=True,
            groups=[],
            display_model_names=[llm_model, fast_model],
            model_names=[llm_model, fast_model],
        )
        new_llm_provider = upsert_llm_provider(
            llm_provider=model_req, db_session=db_session
        )
        update_default_provider(provider_id=new_llm_provider.id, db_session=db_session)


def update_default_multipass_indexing(db_session: Session) -> None:
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    logger.debug(f"Docs exist: {docs_exist}, Connectors exist: {connectors_exist}")

    if not docs_exist and not connectors_exist:
        logger.info(
            "No existing docs or connectors found. Checking GPU availability for multipass indexing."
        )
        gpu_available = gpu_status_request()
        logger.info(f"GPU available: {gpu_available}")

        current_settings = get_current_search_settings(db_session)

        logger.notice(f"Updating multipass indexing setting to: {gpu_available}")
        updated_settings = SavedSearchSettings.from_db_model(current_settings)
        # Enable multipass indexing if GPU is available or if using a cloud provider
        updated_settings.multipass_indexing = (
            gpu_available or current_settings.cloud_provider is not None
        )
        update_current_search_settings(db_session, updated_settings)

    else:
        logger.debug(
            "Existing docs or connectors found. Skipping multipass indexing update."
        )


def translate_saved_search_settings(db_session: Session) -> None:
    kv_store = get_dynamic_config_store()

    try:
        search_settings_dict = kv_store.load(KV_SEARCH_SETTINGS)
        if isinstance(search_settings_dict, dict):
            # Update current search settings
            current_settings = get_current_search_settings(db_session)

            # Update non-preserved fields
            if current_settings:
                current_settings_dict = SavedSearchSettings.from_db_model(
                    current_settings
                ).dict()

                new_current_settings = SavedSearchSettings(
                    **{**current_settings_dict, **search_settings_dict}
                )
                update_current_search_settings(db_session, new_current_settings)

            # Update secondary search settings
            secondary_settings = get_secondary_search_settings(db_session)
            if secondary_settings:
                secondary_settings_dict = SavedSearchSettings.from_db_model(
                    secondary_settings
                ).dict()

                new_secondary_settings = SavedSearchSettings(
                    **{**secondary_settings_dict, **search_settings_dict}
                )
                update_secondary_search_settings(
                    db_session,
                    new_secondary_settings,
                )
            # Delete the KV store entry after successful update
            kv_store.delete(KV_SEARCH_SETTINGS)
            logger.notice("Search settings updated and KV store entry deleted.")
        else:
            logger.notice("KV store search settings is empty.")
    except ConfigNotFoundError:
        logger.notice("No search config found in KV store.")


def mark_reindex_flag(db_session: Session) -> None:
    kv_store = get_dynamic_config_store()
    try:
        value = kv_store.load(KV_REINDEX_KEY)
        logger.debug(f"Re-indexing flag has value {value}")
        return
    except ConfigNotFoundError:
        # Only need to update the flag if it hasn't been set
        pass

    # If their first deployment is after the changes, it will
    # enable this when the other changes go in, need to avoid
    # this being set to False, then the user indexes things on the old version
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    if docs_exist or connectors_exist:
        kv_store.store(KV_REINDEX_KEY, True)
    else:
        kv_store.store(KV_REINDEX_KEY, False)


def setup_vespa(
    document_index: DocumentIndex,
    index_setting: IndexingSetting,
    secondary_index_setting: IndexingSetting | None,
) -> bool:
    # Vespa startup is a bit slow, so give it a few seconds
    WAIT_SECONDS = 5
    VESPA_ATTEMPTS = 5
    for x in range(VESPA_ATTEMPTS):
        try:
            logger.notice(f"Setting up Vespa (attempt {x+1}/{VESPA_ATTEMPTS})...")
            document_index.ensure_indices_exist(
                index_embedding_dim=index_setting.model_dim,
                secondary_index_embedding_dim=secondary_index_setting.model_dim
                if secondary_index_setting
                else None,
            )

            logger.notice("Vespa setup complete.")
            return True
        except Exception:
            logger.notice(
                f"Vespa setup did not succeed. The Vespa service may not be ready yet. Retrying in {WAIT_SECONDS} seconds."
            )
            time.sleep(WAIT_SECONDS)

    logger.error(
        f"Vespa setup did not succeed. Attempt limit reached. ({VESPA_ATTEMPTS})"
    )
    return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    init_sqlalchemy_engine(POSTGRES_WEB_APP_NAME)
    engine = get_sqlalchemy_engine()

    verify_auth = fetch_versioned_implementation(
        "danswer.auth.users", "verify_auth_setting"
    )
    # Will throw exception if an issue is found
    verify_auth()

    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET:
        logger.notice("Both OAuth Client ID and Secret are configured.")

    if DISABLE_GENERATIVE_AI:
        logger.notice("Generative AI Q&A disabled")

    # fill up Postgres connection pools
    await warm_up_connections()

    # We cache this at the beginning so there is no delay in the first telemetry
    get_or_generate_uuid()

    with Session(engine) as db_session:
        check_index_swap(db_session=db_session)
        search_settings = get_current_search_settings(db_session)
        secondary_search_settings = get_secondary_search_settings(db_session)

        # Break bad state for thrashing indexes
        if secondary_search_settings and DISABLE_INDEX_UPDATE_ON_SWAP:
            expire_index_attempts(
                search_settings_id=search_settings.id, db_session=db_session
            )

            for cc_pair in get_connector_credential_pairs(db_session):
                resync_cc_pair(cc_pair, db_session=db_session)

        # Expire all old embedding models indexing attempts, technically redundant
        cancel_indexing_attempts_past_model(db_session)

        logger.notice(f'Using Embedding model: "{search_settings.model_name}"')
        if search_settings.query_prefix or search_settings.passage_prefix:
            logger.notice(f'Query embedding prefix: "{search_settings.query_prefix}"')
            logger.notice(
                f'Passage embedding prefix: "{search_settings.passage_prefix}"'
            )

        if search_settings:
            if not search_settings.disable_rerank_for_streaming:
                logger.notice("Reranking is enabled.")

            if search_settings.multilingual_expansion:
                logger.notice(
                    f"Multilingual query expansion is enabled with {search_settings.multilingual_expansion}."
                )
        if (
            search_settings.rerank_model_name
            and not search_settings.provider_type
            and not search_settings.rerank_provider_type
        ):
            warm_up_cross_encoder(search_settings.rerank_model_name)

        logger.notice("Verifying query preprocessing (NLTK) data is downloaded")
        download_nltk_data()

        # setup Postgres with default credential, llm providers, etc.
        setup_postgres(db_session)

        translate_saved_search_settings(db_session)

        # Does the user need to trigger a reindexing to bring the document index
        # into a good state, marked in the kv store
        mark_reindex_flag(db_session)

        # ensure Vespa is setup correctly
        logger.notice("Verifying Document Index(s) is/are available.")
        document_index = get_default_document_index(
            primary_index_name=search_settings.index_name,
            secondary_index_name=secondary_search_settings.index_name
            if secondary_search_settings
            else None,
        )

        success = setup_vespa(
            document_index,
            IndexingSetting.from_db_model(search_settings),
            IndexingSetting.from_db_model(secondary_search_settings)
            if secondary_search_settings
            else None,
        )
        if not success:
            raise RuntimeError(
                "Could not connect to Vespa within the specified timeout."
            )

        logger.notice(f"Model Server: http://{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")
        if search_settings.provider_type is None:
            warm_up_bi_encoder(
                embedding_model=EmbeddingModel.from_db_model(
                    search_settings=search_settings,
                    server_host=MODEL_SERVER_HOST,
                    server_port=MODEL_SERVER_PORT,
                ),
            )

        # update multipass indexing setting based on GPU availability
        update_default_multipass_indexing(db_session)

    optional_telemetry(record_type=RecordType.VERSION, data={"version": __version__})
    yield


def log_http_error(_: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 500)
    if status_code >= 400:
        error_msg = f"{str(exc)}\n"
        error_msg += "".join(traceback.format_tb(exc.__traceback__))
        logger.error(error_msg)

    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )


def get_application() -> FastAPI:
    application = FastAPI(
        title="Danswer Backend", version=__version__, lifespan=lifespan
    )

    # Add the custom exception handler
    application.add_exception_handler(status.HTTP_400_BAD_REQUEST, log_http_error)
    application.add_exception_handler(status.HTTP_401_UNAUTHORIZED, log_http_error)
    application.add_exception_handler(status.HTTP_403_FORBIDDEN, log_http_error)
    application.add_exception_handler(status.HTTP_404_NOT_FOUND, log_http_error)
    application.add_exception_handler(
        status.HTTP_500_INTERNAL_SERVER_ERROR, log_http_error
    )

    include_router_with_global_prefix_prepended(application, chat_router)
    include_router_with_global_prefix_prepended(application, query_router)
    include_router_with_global_prefix_prepended(application, document_router)
    include_router_with_global_prefix_prepended(application, admin_query_router)
    include_router_with_global_prefix_prepended(application, admin_router)
    include_router_with_global_prefix_prepended(application, user_router)
    include_router_with_global_prefix_prepended(application, connector_router)
    include_router_with_global_prefix_prepended(application, credential_router)
    include_router_with_global_prefix_prepended(application, cc_pair_router)
    include_router_with_global_prefix_prepended(application, folder_router)
    include_router_with_global_prefix_prepended(application, document_set_router)
    include_router_with_global_prefix_prepended(application, search_settings_router)
    include_router_with_global_prefix_prepended(
        application, slack_bot_management_router
    )
    include_router_with_global_prefix_prepended(application, persona_router)
    include_router_with_global_prefix_prepended(application, admin_persona_router)
    include_router_with_global_prefix_prepended(application, input_prompt_router)
    include_router_with_global_prefix_prepended(application, admin_input_prompt_router)
    include_router_with_global_prefix_prepended(application, prompt_router)
    include_router_with_global_prefix_prepended(application, tool_router)
    include_router_with_global_prefix_prepended(application, admin_tool_router)
    include_router_with_global_prefix_prepended(application, state_router)
    include_router_with_global_prefix_prepended(application, danswer_api_router)
    include_router_with_global_prefix_prepended(application, gpts_router)
    include_router_with_global_prefix_prepended(application, settings_router)
    include_router_with_global_prefix_prepended(application, settings_admin_router)
    include_router_with_global_prefix_prepended(application, llm_admin_router)
    include_router_with_global_prefix_prepended(application, llm_router)
    include_router_with_global_prefix_prepended(application, embedding_admin_router)
    include_router_with_global_prefix_prepended(application, embedding_router)
    include_router_with_global_prefix_prepended(
        application, token_rate_limit_settings_router
    )
    include_router_with_global_prefix_prepended(application, indexing_router)

    include_router_with_global_prefix_prepended(application, eea_config_router)

    if AUTH_TYPE == AuthType.DISABLED:
        # Server logs this during auth setup verification step
        pass

    elif AUTH_TYPE == AuthType.BASIC:
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_auth_router(auth_backend),
            prefix="/auth",
            tags=["auth"],
        )
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_register_router(UserRead, UserCreate),
            prefix="/auth",
            tags=["auth"],
        )
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_reset_password_router(),
            prefix="/auth",
            tags=["auth"],
        )
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_verify_router(UserRead),
            prefix="/auth",
            tags=["auth"],
        )
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_users_router(UserRead, UserUpdate),
            prefix="/users",
            tags=["users"],
        )

    elif AUTH_TYPE == AuthType.GOOGLE_OAUTH:
        oauth_client = GoogleOAuth2(OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET)
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_oauth_router(
                oauth_client,
                auth_backend,
                USER_AUTH_SECRET,
                associate_by_email=True,
                is_verified_by_default=True,
                # Points the user back to the login page
                redirect_url=f"{WEB_DOMAIN}/auth/oauth/callback",
            ),
            prefix="/auth/oauth",
            tags=["auth"],
        )
        # Need basic auth router for `logout` endpoint
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_logout_router(auth_backend),
            prefix="/auth",
            tags=["auth"],
        )

    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )

    application.add_exception_handler(ValueError, value_error_handler)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Change this to the list of allowed origins if needed
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if LOG_ENDPOINT_LATENCY:
        add_latency_logging_middleware(application, logger)

    # Ensure all routes have auth enabled or are explicitly marked as public
    check_router_auth(application)

    return application


# NOTE: needs to be outside of the `if __name__ == "__main__"` block so that the
# app is exportable
set_is_ee_based_on_env_variable()
app = fetch_versioned_implementation(module="danswer.main", attribute="get_application")


if __name__ == "__main__":
    logger.notice(
        f"Starting Danswer Backend version {__version__} on http://{APP_HOST}:{str(APP_PORT)}/"
    )

    if global_version.get_is_ee_version():
        logger.notice("Running Enterprise Edition")

    uvicorn.run(app, host=APP_HOST, port=APP_PORT)
