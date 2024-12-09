import sys
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from typing import cast

import sentry_sdk
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
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sqlalchemy.orm import Session

from danswer import __version__
from danswer.auth.schemas import UserCreate
from danswer.auth.schemas import UserRead
from danswer.auth.schemas import UserUpdate
from danswer.auth.users import auth_backend
from danswer.auth.users import BasicAuthenticationError
from danswer.auth.users import fastapi_users
from danswer.configs.app_configs import APP_API_PREFIX
from danswer.configs.app_configs import APP_HOST
from danswer.configs.app_configs import APP_PORT
from danswer.configs.app_configs import AUTH_TYPE
from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.app_configs import LOG_ENDPOINT_LATENCY
from danswer.configs.app_configs import OAUTH_CLIENT_ID
from danswer.configs.app_configs import OAUTH_CLIENT_SECRET
from danswer.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from danswer.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from danswer.configs.app_configs import SYSTEM_RECURSION_LIMIT
from danswer.configs.app_configs import USER_AUTH_SECRET
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.configs.constants import AuthType
from danswer.configs.constants import POSTGRES_WEB_APP_NAME
from danswer.db.engine import SqlEngine
from danswer.db.engine import warm_up_connections
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
from danswer.server.features.notifications.api import router as notification_router
from danswer.server.features.persona.api import admin_router as admin_persona_router
from danswer.server.features.persona.api import basic_router as persona_router
from danswer.server.features.prompt.api import basic_router as prompt_router
from danswer.server.features.tool.api import admin_router as admin_tool_router
from danswer.server.features.tool.api import router as tool_router
from danswer.server.gpts.api import router as gpts_router
from danswer.server.long_term_logs.long_term_logs_api import (
    router as long_term_logs_router,
)
from danswer.server.manage.administrative import router as admin_router
from danswer.server.manage.embedding.api import admin_router as embedding_admin_router
from danswer.server.manage.embedding.api import basic_router as embedding_router
from danswer.server.manage.get_state import router as state_router
from danswer.server.manage.llm.api import admin_router as llm_admin_router
from danswer.server.manage.llm.api import basic_router as llm_router
from danswer.server.manage.search_settings import router as search_settings_router
from danswer.server.manage.slack_bot import router as slack_bot_management_router
from danswer.server.manage.users import router as user_router
from danswer.server.middleware.latency_logging import add_latency_logging_middleware
from danswer.server.openai_assistants_api.full_openai_assistants_api import (
    get_full_openai_assistants_api_router,
)
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
from danswer.setup import setup_danswer
from danswer.setup import setup_multitenant_danswer
from danswer.utils.logger import setup_logger
from danswer.utils.telemetry import get_or_generate_uuid
from danswer.utils.telemetry import optional_telemetry
from danswer.utils.telemetry import RecordType
from danswer.utils.variable_functionality import fetch_versioned_implementation
from danswer.utils.variable_functionality import global_version
from danswer.utils.variable_functionality import set_is_ee_based_on_env_variable
from shared_configs.configs import CORS_ALLOWED_ORIGIN
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SENTRY_DSN

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # Set recursion limit
    if SYSTEM_RECURSION_LIMIT is not None:
        sys.setrecursionlimit(SYSTEM_RECURSION_LIMIT)
        logger.notice(f"System recursion limit set to {SYSTEM_RECURSION_LIMIT}")

    SqlEngine.set_app_name(POSTGRES_WEB_APP_NAME)
    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )
    engine = SqlEngine.get_engine()

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

    if not MULTI_TENANT:
        # We cache this at the beginning so there is no delay in the first telemetry
        get_or_generate_uuid()

        # If we are multi-tenant, we need to only set up initial public tables
        with Session(engine) as db_session:
            setup_danswer(db_session, None)
    else:
        setup_multitenant_danswer()

    optional_telemetry(record_type=RecordType.VERSION, data={"version": __version__})
    yield


def log_http_error(_: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 500)

    if isinstance(exc, BasicAuthenticationError):
        # For BasicAuthenticationError, just log a brief message without stack trace (almost always spam)
        logger.error(f"Authentication failed: {str(exc)}")

    elif status_code >= 400:
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
    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.1,
        )
        logger.info("Sentry initialized")
    else:
        logger.debug("Sentry DSN not provided, skipping Sentry initialization")

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
    include_router_with_global_prefix_prepended(application, notification_router)
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
    include_router_with_global_prefix_prepended(
        application, get_full_openai_assistants_api_router()
    )
    include_router_with_global_prefix_prepended(application, long_term_logs_router)

    include_router_with_global_prefix_prepended(application, eea_config_router)

    if AUTH_TYPE == AuthType.DISABLED:
        # Server logs this during auth setup verification step
        pass

    if AUTH_TYPE == AuthType.BASIC or AUTH_TYPE == AuthType.CLOUD:
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

    if AUTH_TYPE == AuthType.GOOGLE_OAUTH:
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
        allow_origins=CORS_ALLOWED_ORIGIN,  # Configurable via environment variable
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

    if global_version.is_ee_version():
        logger.notice("Running Enterprise Edition")

    uvicorn.run(app, host=APP_HOST, port=APP_PORT)
