from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from typing import cast

import nltk  # type:ignore
import torch  # Import here is fine, API server needs torch anyway and nothing imports main.py
import uvicorn
from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import Request
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
from danswer.configs.app_configs import MODEL_SERVER_HOST
from danswer.configs.app_configs import MODEL_SERVER_PORT
from danswer.configs.app_configs import OAUTH_CLIENT_ID
from danswer.configs.app_configs import OAUTH_CLIENT_SECRET
from danswer.configs.app_configs import SECRET
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.configs.chat_configs import MULTILINGUAL_QUERY_EXPANSION
from danswer.configs.constants import AuthType
from danswer.configs.model_configs import ENABLE_RERANKING_REAL_TIME_FLOW
from danswer.configs.model_configs import GEN_AI_API_ENDPOINT
from danswer.configs.model_configs import GEN_AI_MODEL_PROVIDER
from danswer.db.chat import delete_old_default_personas
from danswer.db.connector import create_initial_default_connector
from danswer.db.connector_credential_pair import associate_default_cc_pair
from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.connector_credential_pair import resync_cc_pair
from danswer.db.credentials import create_initial_public_credential
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.embedding_model import get_secondary_db_embedding_model
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.index_attempt import cancel_indexing_attempts_past_model
from danswer.db.index_attempt import expire_index_attempts
from danswer.document_index.factory import get_default_document_index
from danswer.dynamic_configs.port_configs import port_filesystem_to_postgres
from danswer.llm.factory import get_default_llm
from danswer.llm.utils import get_default_llm_version
from danswer.search.search_nlp_models import warm_up_models
from danswer.server.danswer_api.ingestion import get_danswer_api_key
from danswer.server.danswer_api.ingestion import router as danswer_api_router
from danswer.server.documents.cc_pair import router as cc_pair_router
from danswer.server.documents.connector import router as connector_router
from danswer.server.documents.credential import router as credential_router
from danswer.server.documents.document import router as document_router
from danswer.server.features.document_set.api import router as document_set_router
from danswer.server.features.persona.api import admin_router as admin_persona_router
from danswer.server.features.persona.api import basic_router as persona_router
from danswer.server.features.prompt.api import basic_router as prompt_router
from danswer.server.gpts.api import router as gpts_router
from danswer.server.manage.administrative import router as admin_router
from danswer.server.manage.get_state import router as state_router
from danswer.server.manage.secondary_index import router as secondary_index_router
from danswer.server.manage.slack_bot import router as slack_bot_management_router
from danswer.server.manage.users import router as user_router
from danswer.server.query_and_chat.chat_backend import router as chat_router
from danswer.server.query_and_chat.query_backend import (
    admin_router as admin_query_router,
)
from danswer.server.query_and_chat.query_backend import basic_router as query_router
from danswer.utils.logger import setup_logger
from danswer.utils.telemetry import optional_telemetry
from danswer.utils.telemetry import RecordType
from danswer.utils.variable_functionality import fetch_versioned_implementation


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    engine = get_sqlalchemy_engine()

    verify_auth = fetch_versioned_implementation(
        "danswer.auth.users", "verify_auth_setting"
    )
    # Will throw exception if an issue is found
    verify_auth()

    # Danswer APIs key
    api_key = get_danswer_api_key()
    logger.info(f"Danswer API Key: {api_key}")

    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET:
        logger.info("Both OAuth Client ID and Secret are configured.")

    if DISABLE_GENERATIVE_AI:
        logger.info("Generative AI Q&A disabled")
    else:
        logger.info(f"Using LLM Provider: {GEN_AI_MODEL_PROVIDER}")
        base, fast = get_default_llm_version()
        logger.info(f"Using LLM Model Version: {base}")
        if base != fast:
            logger.info(f"Using Fast LLM Model Version: {fast}")
        if GEN_AI_API_ENDPOINT:
            logger.info(f"Using LLM Endpoint: {GEN_AI_API_ENDPOINT}")

        # Any additional model configs logged here
        get_default_llm().log_model_configs()

    if MULTILINGUAL_QUERY_EXPANSION:
        logger.info(
            f"Using multilingual flow with languages: {MULTILINGUAL_QUERY_EXPANSION}"
        )

    port_filesystem_to_postgres()

    with Session(engine) as db_session:
        db_embedding_model = get_current_db_embedding_model(db_session)
        secondary_db_embedding_model = get_secondary_db_embedding_model(db_session)

        # Break bad state for thrashing indexes
        if secondary_db_embedding_model and DISABLE_INDEX_UPDATE_ON_SWAP:
            expire_index_attempts(
                embedding_model_id=db_embedding_model.id, db_session=db_session
            )

            for cc_pair in get_connector_credential_pairs(db_session):
                resync_cc_pair(cc_pair, db_session=db_session)

        # Expire all old embedding models indexing attempts, technically redundant
        cancel_indexing_attempts_past_model(db_session)

        logger.info(f'Using Embedding model: "{db_embedding_model.model_name}"')
        if db_embedding_model.query_prefix or db_embedding_model.passage_prefix:
            logger.info(f'Query embedding prefix: "{db_embedding_model.query_prefix}"')
            logger.info(
                f'Passage embedding prefix: "{db_embedding_model.passage_prefix}"'
            )

        if ENABLE_RERANKING_REAL_TIME_FLOW:
            logger.info("Reranking step of search flow is enabled.")

        if MODEL_SERVER_HOST:
            logger.info(
                f"Using Model Server: http://{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}"
            )
        else:
            logger.info("Warming up local NLP models.")
            warm_up_models(
                model_name=db_embedding_model.model_name,
                normalize=db_embedding_model.normalize,
                skip_cross_encoders=not ENABLE_RERANKING_REAL_TIME_FLOW,
            )

            if torch.cuda.is_available():
                logger.info("GPU is available")
            else:
                logger.info("GPU is not available")
            logger.info(f"Torch Threads: {torch.get_num_threads()}")

        logger.info("Verifying query preprocessing (NLTK) data is downloaded")
        nltk.download("stopwords", quiet=True)
        nltk.download("wordnet", quiet=True)
        nltk.download("punkt", quiet=True)

        logger.info("Verifying default connector/credential exist.")
        create_initial_public_credential(db_session)
        create_initial_default_connector(db_session)
        associate_default_cc_pair(db_session)

        logger.info("Loading default Prompts and Personas")
        delete_old_default_personas(db_session)
        load_chat_yamls()

        logger.info("Verifying Document Index(s) is/are available.")

        document_index = get_default_document_index(
            primary_index_name=db_embedding_model.index_name,
            secondary_index_name=secondary_db_embedding_model.index_name
            if secondary_db_embedding_model
            else None,
        )
        document_index.ensure_indices_exist(
            index_embedding_dim=db_embedding_model.model_dim,
            secondary_index_embedding_dim=secondary_db_embedding_model.model_dim
            if secondary_db_embedding_model
            else None,
        )

    optional_telemetry(record_type=RecordType.VERSION, data={"version": __version__})

    yield


def get_application() -> FastAPI:
    application = FastAPI(
        title="Danswer Backend", version=__version__, lifespan=lifespan
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
    include_router_with_global_prefix_prepended(application, document_set_router)
    include_router_with_global_prefix_prepended(application, secondary_index_router)
    include_router_with_global_prefix_prepended(
        application, slack_bot_management_router
    )
    include_router_with_global_prefix_prepended(application, persona_router)
    include_router_with_global_prefix_prepended(application, admin_persona_router)
    include_router_with_global_prefix_prepended(application, prompt_router)
    include_router_with_global_prefix_prepended(application, state_router)
    include_router_with_global_prefix_prepended(application, danswer_api_router)
    include_router_with_global_prefix_prepended(application, gpts_router)

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
                SECRET,
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

    return application


app = get_application()


if __name__ == "__main__":
    logger.info(
        f"Starting Danswer Backend version {__version__} on http://{APP_HOST}:{str(APP_PORT)}/"
    )
    uvicorn.run(app, host=APP_HOST, port=APP_PORT)
