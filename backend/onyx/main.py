import logging
import sys
import traceback
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import uvicorn
from anyio import to_thread
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from httpx_oauth.clients.google import GoogleOAuth2
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette.types import Lifespan

from onyx import __version__
from onyx.auth.schemas import AuthBackend, UserCreate, UserRead, UserUpdate
from onyx.auth.users import (
    auth_backend,
    create_onyx_oauth_router,
    fastapi_users,
    mobile_auth_backend,
    verify_auth_setting,
    verify_user_auth_secret,
)
from onyx.cache.interface import CacheBackendType
from onyx.configs.app_configs import (
    API_SERVER_THREADPOOL_SIZE,
    APP_API_PREFIX,
    APP_HOST,
    APP_PORT,
    AUTH_BACKEND,
    CACHE_BACKEND,
    DISABLE_VECTOR_DB,
    ENABLE_PUBLIC_DOCS,
    GOOGLE_LOGIN_BASE_SCOPES,
    GOOGLE_OAUTH_SCOPE_OVERRIDE,
    LOG_ENDPOINT_LATENCY,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_ENABLED,
    POSTGRES_API_SERVER_POOL_OVERFLOW,
    POSTGRES_API_SERVER_POOL_SIZE,
    POSTGRES_API_SERVER_READ_ONLY_POOL_OVERFLOW,
    POSTGRES_API_SERVER_READ_ONLY_POOL_SIZE,
    SYSTEM_RECURSION_LIMIT,
    USER_AUTH_SECRET,
    WEB_DOMAIN,
)
from onyx.configs.constants import POSTGRES_WEB_APP_NAME
from onyx.db.engine.async_sql_engine import (
    get_sqlalchemy_async_engine,
    reset_sqlalchemy_async_engine,
)
from onyx.db.engine.connection_warmup import warm_up_connections
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.sso_provider import seed_saml_provider_from_conf_dir
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.file_store.file_store import get_default_file_store
from onyx.hooks.registry import validate_registry
from onyx.redis.redis_pool import log_redis_server_diagnostics
from onyx.server.api_key.api import router as api_key_router
from onyx.server.auth.captcha_api import CaptchaCookieMiddleware, LoginCaptchaMiddleware
from onyx.server.auth.captcha_api import router as captcha_router
from onyx.server.auth.mobile import router as mobile_auth_router
from onyx.server.auth_check import check_router_auth
from onyx.server.documents.cc_pair import router as cc_pair_router
from onyx.server.documents.connector import router as connector_router
from onyx.server.documents.credential import router as credential_router
from onyx.server.documents.document import router as document_router
from onyx.server.documents.standard_oauth import router as standard_oauth_router
from onyx.server.documents.targeted_reindex import router as targeted_reindex_router
from onyx.server.features.admin_banner.api import admin_router as admin_banner_router
from onyx.server.features.build.api import admin_router as build_admin_router
from onyx.server.features.build.api import router as build_router
from onyx.server.features.build.webapp_proxy import public_build_router
from onyx.server.features.default_assistant.api import (
    router as default_assistant_router,
)
from onyx.server.features.document_set.api import router as document_set_router
from onyx.server.features.hierarchy.api import router as hierarchy_router
from onyx.server.features.image_generation.api import router as image_generation_router
from onyx.server.features.input_prompt.api import (
    admin_router as admin_input_prompt_router,
)
from onyx.server.features.input_prompt.api import basic_router as input_prompt_router
from onyx.server.features.mcp.api import admin_router as mcp_admin_router
from onyx.server.features.mcp.api import router as mcp_router
from onyx.server.features.notifications.api import router as notification_router
from onyx.server.features.oauth_config.api import (
    admin_router as admin_oauth_config_router,
)
from onyx.server.features.oauth_config.api import router as oauth_config_router
from onyx.server.features.password.api import router as password_router
from onyx.server.features.persona.api import admin_agents_router, agents_router
from onyx.server.features.persona.api import admin_router as admin_persona_router
from onyx.server.features.persona.api import basic_router as persona_router
from onyx.server.features.projects.api import router as projects_router
from onyx.server.features.search.api import router as search_api_router
from onyx.server.features.skill.api import user_router as skill_router
from onyx.server.features.tool.api import admin_router as admin_tool_router
from onyx.server.features.tool.api import router as tool_router
from onyx.server.features.usage.api import admin_usage_router, user_usage_router
from onyx.server.features.usage.api import router as cost_override_router
from onyx.server.features.user_oauth_token.api import router as user_oauth_token_router
from onyx.server.features.web_search.api import router as web_search_router
from onyx.server.federated.api import router as federated_router
from onyx.server.kg.api import admin_router as kg_admin_router
from onyx.server.manage.administrative import router as admin_router
from onyx.server.manage.code_interpreter.api import (
    admin_router as code_interpreter_admin_router,
)
from onyx.server.manage.discord_bot.api import router as discord_bot_router
from onyx.server.manage.embedding.api import admin_router as embedding_admin_router
from onyx.server.manage.embedding.api import basic_router as embedding_router
from onyx.server.manage.get_state import router as state_router
from onyx.server.manage.image_generation.api import (
    admin_router as image_generation_admin_router,
)
from onyx.server.manage.llm.api import admin_router as llm_admin_router
from onyx.server.manage.llm.api import basic_router as llm_router
from onyx.server.manage.oauth_test import router as oauth_test_admin_router
from onyx.server.manage.opensearch_migration.api import (
    admin_router as opensearch_migration_admin_router,
)
from onyx.server.manage.search_settings import router as search_settings_router
from onyx.server.manage.slack_bot import router as slack_bot_management_router
from onyx.server.manage.sso.api import admin_router as sso_admin_router
from onyx.server.manage.tracing.api import admin_router as tracing_admin_router
from onyx.server.manage.users import router as user_router
from onyx.server.manage.voice.api import admin_router as voice_admin_router
from onyx.server.manage.voice.user_api import router as voice_router
from onyx.server.manage.voice.websocket_api import router as voice_websocket_router
from onyx.server.manage.web_search.api import admin_router as web_search_admin_router
from onyx.server.metrics.connector_state_metrics import register_connector_state_metrics
from onyx.server.metrics.postgres_connection_pool import (
    setup_postgres_connection_pool_metrics,
)
from onyx.server.metrics.prometheus_setup import setup_prometheus_metrics
from onyx.server.middleware.latency_logging import add_latency_logging_middleware
from onyx.server.middleware.rate_limiting import (
    RATE_LIMITING_ENABLED,
    close_auth_limiter,
    get_auth_rate_limiters,
    setup_auth_limiter,
)
from onyx.server.oidc_multi import router as oidc_multi_router
from onyx.server.onyx_api.ingestion import router as onyx_api_router
from onyx.server.pat.api import router as pat_router
from onyx.server.query_and_chat.chat_backend import router as chat_router
from onyx.server.query_and_chat.query_backend import admin_router as admin_query_router
from onyx.server.query_and_chat.query_backend import basic_router as query_router
from onyx.server.saml_multi import router as saml_multi_router
from onyx.server.security.api import admin_router as security_admin_router
from onyx.server.settings.api import admin_router as settings_admin_router
from onyx.server.settings.api import basic_router as settings_router
from onyx.server.token_rate_limits.api import router as token_rate_limit_settings_router
from onyx.server.utils import BasicAuthenticationError
from onyx.setup import setup_multitenant_onyx, setup_onyx
from onyx.tracing.setup import setup_tracing
from onyx.utils.client_ip import ClientIPMiddleware
from onyx.utils.logger import setup_logger, setup_uvicorn_logger
from onyx.utils.middleware import (
    add_endpoint_context_middleware,
    add_onyx_request_id_middleware,
)
from onyx.utils.telemetry import RecordType, get_or_generate_uuid, optional_telemetry
from onyx.utils.variable_functionality import (
    fetch_ee_implementation_or_noop,
    fetch_versioned_implementation,
    global_version,
    set_is_ee_based_on_env_variable,
)
from shared_configs.configs import (
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOWED_ORIGIN,
    MULTI_TENANT,
    POSTGRES_DEFAULT_SCHEMA,
    SENTRY_DSN,
    SENTRY_TRACES_SAMPLE_RATE,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

warnings.filterwarnings(
    "ignore", category=ResourceWarning, message=r"Unclosed client session"
)
warnings.filterwarnings(
    "ignore", category=ResourceWarning, message=r"Unclosed connector"
)

logger = setup_logger()

file_handlers = [
    h for h in logger.logger.handlers if isinstance(h, logging.FileHandler)
]

setup_uvicorn_logger(shared_file_handlers=file_handlers)


def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        logger.error(
            "Unexpected exception type in validation_exception_handler - %s", type(exc)
        )
        raise exc

    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    logger.exception("%s: %s", request, exc_str)
    content = {"status_code": 422, "message": exc_str, "data": None}
    return JSONResponse(content=content, status_code=422)


def value_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ValueError):
        logger.error("Unexpected exception type in value_error_handler - %s", type(exc))
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


def use_route_function_names_as_operation_ids(app: FastAPI) -> None:
    """
    OpenAPI generation defaults to naming the operation with the
    function + route + HTTP method, which usually looks very redundant.

    This function changes the operation IDs to be just the function name.

    Should be called only after all routes have been added.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.operation_id = route.name


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


def include_auth_router_with_prefix(
    application: FastAPI,
    router: APIRouter,
    prefix: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Wrapper function to include an 'auth' router with prefix + rate-limiting dependencies."""
    final_tags = tags or ["auth"]
    include_router_with_global_prefix_prepended(
        application,
        router,
        prefix=prefix,
        tags=final_tags,
        dependencies=get_auth_rate_limiters(),
    )


def validate_cache_backend_settings() -> None:
    """Validate that CACHE_BACKEND=postgres is only used with DISABLE_VECTOR_DB.

    The Postgres cache backend eliminates the Redis dependency, but only works
    when Celery is not running (which requires DISABLE_VECTOR_DB=true).
    """
    if CACHE_BACKEND == CacheBackendType.POSTGRES and not DISABLE_VECTOR_DB:
        raise RuntimeError(
            "CACHE_BACKEND=postgres requires DISABLE_VECTOR_DB=true. "
            "The Postgres cache backend is only supported in no-vector-DB "
            "deployments where Celery is replaced by the in-process task runner."
        )


def validate_no_vector_db_settings() -> None:
    """Validate that DISABLE_VECTOR_DB is not combined with incompatible settings.

    Raises RuntimeError if DISABLE_VECTOR_DB is set alongside MULTI_TENANT or ENABLE_CRAFT,
    since these modes require infrastructure that is removed in no-vector-DB deployments.
    """
    if not DISABLE_VECTOR_DB:
        return

    if MULTI_TENANT:
        raise RuntimeError(
            "DISABLE_VECTOR_DB cannot be used with MULTI_TENANT. "
            "Multi-tenant deployments require the vector database for "
            "per-tenant document indexing and search. Run in single-tenant "
            "mode when disabling the vector database."
        )

    from onyx.server.features.build.configs import ENABLE_CRAFT

    if ENABLE_CRAFT:
        raise RuntimeError(
            "DISABLE_VECTOR_DB cannot be used with ENABLE_CRAFT. "
            "Onyx Craft requires background workers for sandbox lifecycle "
            "management, which are removed in no-vector-DB deployments. "
            "Disable Craft (ENABLE_CRAFT=false) when disabling the vector database."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    validate_no_vector_db_settings()
    validate_cache_backend_settings()
    validate_registry()

    # Set recursion limit
    if SYSTEM_RECURSION_LIMIT is not None:
        sys.setrecursionlimit(SYSTEM_RECURSION_LIMIT)
        logger.notice("System recursion limit set to %s", SYSTEM_RECURSION_LIMIT)

    # Size the anyio threadpool that serves sync endpoints (incl. the streaming
    # chat generator). Must run inside the event loop, as the limiter is per-loop.
    if API_SERVER_THREADPOOL_SIZE > 0:
        to_thread.current_default_thread_limiter().total_tokens = (
            API_SERVER_THREADPOOL_SIZE
        )
        logger.notice(
            "API server threadpool size set to %s", API_SERVER_THREADPOOL_SIZE
        )

    SqlEngine.set_app_name(POSTGRES_WEB_APP_NAME)

    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )
    SqlEngine.get_engine()

    SqlEngine.init_readonly_engine(
        pool_size=POSTGRES_API_SERVER_READ_ONLY_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_READ_ONLY_POOL_OVERFLOW,
    )

    # Register pool metrics now that engines are created.
    # HTTP instrumentation is set up earlier in get_application() since it
    # adds middleware (which Starlette forbids after the app has started).
    register_connector_state_metrics()
    setup_postgres_connection_pool_metrics(
        engines={
            "sync": SqlEngine.get_engine(),
            "async": get_sqlalchemy_async_engine(),
            "readonly": SqlEngine.get_readonly_engine(),
        },
    )

    # Self-hosted license seat + expiry gauges on /metrics (EE-only, no-op on CE)
    fetch_ee_implementation_or_noop(
        "onyx.server.metrics.license_metrics", "register_license_metrics"
    )()

    # Warns on stale AUTH_TYPE env values.
    verify_auth_setting()

    # Will throw exception if USER_AUTH_SECRET is missing on a real deployment
    verify_user_auth_secret()

    # Surface Redis configs that can silently drop session keys. Only relevant
    # when sessions live in Redis; lite deployments may not run Redis at all.
    if AUTH_BACKEND == AuthBackend.REDIS:
        await log_redis_server_diagnostics()

    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET:
        logger.notice("Both OAuth Client ID and Secret are configured.")

    # Initialize tracing if credentials are provided
    setup_tracing()

    # fill up Postgres connection pools
    await warm_up_connections()

    if not MULTI_TENANT:
        # We cache this at the beginning so there is no delay in the first telemetry
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
        get_or_generate_uuid()

        # If we are multi-tenant, we need to only set up initial public tables
        with get_session_with_current_tenant() as db_session:
            setup_onyx(db_session, POSTGRES_DEFAULT_SCHEMA)
            # Import a legacy single-config SAML_CONF_DIR into a provider row. The
            # api_server has the mount the migration job lacks, so this is where it
            # runs. No-op unless AUTH_TYPE=saml with no SAML row yet.
            seed_saml_provider_from_conf_dir(db_session)
            # set up the file store (e.g. create bucket if needed). On multi-tenant,
            # this is done via IaC
            get_default_file_store().initialize()
    else:
        setup_multitenant_onyx()

    if not MULTI_TENANT:
        # don't emit a metric for every pod rollover/restart
        optional_telemetry(
            record_type=RecordType.VERSION, data={"version": __version__}
        )

    if RATE_LIMITING_ENABLED:
        await setup_auth_limiter()

    if DISABLE_VECTOR_DB:
        from onyx.background.periodic_poller import (
            recover_stuck_user_files,
            start_periodic_poller,
        )

        recover_stuck_user_files(POSTGRES_DEFAULT_SCHEMA)
        start_periodic_poller(POSTGRES_DEFAULT_SCHEMA)

    yield

    # Flush buffered per-user usage before disposing the DB engines its drain
    # thread writes through.
    from onyx.tracing.setup import shutdown_tracing

    shutdown_tracing()

    if DISABLE_VECTOR_DB:
        from onyx.background.periodic_poller import stop_periodic_poller

        stop_periodic_poller()

    # Dispose every Postgres connection pool we opened in startup. Order:
    # async first (its disposal is awaitable and can block), then the two
    # sync engines. Each dispose() is wrapped so one failure cannot leak the
    # remaining pools — this path runs on every uvicorn ``--reload`` worker
    # shutdown, and any leaked pool accumulates until PG hits max_connections.
    try:
        await reset_sqlalchemy_async_engine()
    except Exception:
        logger.exception("Failed to dispose async SQLAlchemy engine on shutdown")
    try:
        SqlEngine.reset_engine()
    except Exception:
        logger.exception("Failed to dispose sync SQLAlchemy engine on shutdown")
    try:
        SqlEngine.reset_readonly_engine()
    except Exception:
        logger.exception("Failed to dispose readonly SQLAlchemy engine on shutdown")

    if RATE_LIMITING_ENABLED:
        await close_auth_limiter()


def log_http_error(request: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 500)

    if isinstance(exc, BasicAuthenticationError):
        # For BasicAuthenticationError, just log a brief message without stack trace
        # (almost always spammy)
        logger.debug("Authentication failed: %s", str(exc))

    elif status_code == 404 and request.url.path == "/metrics":
        # Log 404 errors for the /metrics endpoint with debug level
        logger.debug("404 error for /metrics endpoint: %s", str(exc))

    elif status_code >= 400:
        error_msg = f"{str(exc)}\n"
        error_msg += "".join(traceback.format_tb(exc.__traceback__))
        logger.error(error_msg)

    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )


def get_application(lifespan_override: Lifespan | None = None) -> FastAPI:
    application = FastAPI(
        title="Onyx Backend",
        version=__version__,
        description="Onyx API for AI-powered chat with search, document indexing, agents, actions, and more",
        servers=[
            {"url": f"{WEB_DOMAIN.rstrip('/')}/api", "description": "Onyx API Server"}
        ],
        # The interactive docs and schema are opt-in (see ENABLE_PUBLIC_DOCS).
        # When disabled, these routes are not registered at all (404), so the
        # API surface is not exposed publicly on a default deployment.
        openapi_url="/openapi.json" if ENABLE_PUBLIC_DOCS else None,
        docs_url="/docs" if ENABLE_PUBLIC_DOCS else None,
        redoc_url="/redoc" if ENABLE_PUBLIC_DOCS else None,
        lifespan=lifespan_override or lifespan,
    )
    if SENTRY_DSN:
        from onyx.configs.sentry import init_sentry

        init_sentry(
            traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
            integrations=[StarletteIntegration(), FastApiIntegration()],
        )
    else:
        logger.debug("Sentry DSN not provided, skipping Sentry initialization")

    application.add_exception_handler(status.HTTP_400_BAD_REQUEST, log_http_error)
    application.add_exception_handler(status.HTTP_401_UNAUTHORIZED, log_http_error)
    application.add_exception_handler(status.HTTP_403_FORBIDDEN, log_http_error)
    application.add_exception_handler(status.HTTP_404_NOT_FOUND, log_http_error)
    application.add_exception_handler(
        status.HTTP_500_INTERNAL_SERVER_ERROR, log_http_error
    )

    register_onyx_exception_handlers(application)

    include_router_with_global_prefix_prepended(application, password_router)
    include_router_with_global_prefix_prepended(application, chat_router)
    include_router_with_global_prefix_prepended(application, query_router)
    include_router_with_global_prefix_prepended(application, document_router)
    include_router_with_global_prefix_prepended(application, user_router)
    include_router_with_global_prefix_prepended(application, oauth_test_admin_router)
    include_router_with_global_prefix_prepended(application, admin_query_router)
    include_router_with_global_prefix_prepended(application, admin_router)
    include_router_with_global_prefix_prepended(application, connector_router)
    include_router_with_global_prefix_prepended(application, credential_router)
    include_router_with_global_prefix_prepended(application, input_prompt_router)
    include_router_with_global_prefix_prepended(application, admin_input_prompt_router)
    include_router_with_global_prefix_prepended(application, cc_pair_router)
    include_router_with_global_prefix_prepended(application, targeted_reindex_router)
    include_router_with_global_prefix_prepended(application, projects_router)
    include_router_with_global_prefix_prepended(application, public_build_router)
    include_router_with_global_prefix_prepended(application, build_router)
    include_router_with_global_prefix_prepended(application, build_admin_router)
    include_router_with_global_prefix_prepended(application, image_generation_router)
    include_router_with_global_prefix_prepended(application, document_set_router)
    include_router_with_global_prefix_prepended(application, hierarchy_router)
    include_router_with_global_prefix_prepended(application, search_api_router)
    include_router_with_global_prefix_prepended(application, search_settings_router)
    include_router_with_global_prefix_prepended(
        application, slack_bot_management_router
    )
    include_router_with_global_prefix_prepended(application, discord_bot_router)
    include_router_with_global_prefix_prepended(application, persona_router)
    include_router_with_global_prefix_prepended(application, admin_persona_router)
    include_router_with_global_prefix_prepended(application, agents_router)
    include_router_with_global_prefix_prepended(application, admin_agents_router)
    include_router_with_global_prefix_prepended(application, default_assistant_router)
    include_router_with_global_prefix_prepended(application, notification_router)
    include_router_with_global_prefix_prepended(application, admin_banner_router)
    include_router_with_global_prefix_prepended(application, tool_router)
    include_router_with_global_prefix_prepended(application, admin_tool_router)
    include_router_with_global_prefix_prepended(application, oauth_config_router)
    include_router_with_global_prefix_prepended(application, admin_oauth_config_router)
    include_router_with_global_prefix_prepended(application, user_oauth_token_router)
    include_router_with_global_prefix_prepended(application, state_router)
    include_router_with_global_prefix_prepended(application, onyx_api_router)
    include_router_with_global_prefix_prepended(application, settings_router)
    include_router_with_global_prefix_prepended(application, settings_admin_router)
    include_router_with_global_prefix_prepended(application, security_admin_router)
    include_router_with_global_prefix_prepended(application, sso_admin_router)
    include_router_with_global_prefix_prepended(application, llm_admin_router)
    include_router_with_global_prefix_prepended(application, kg_admin_router)
    include_router_with_global_prefix_prepended(application, llm_router)
    include_router_with_global_prefix_prepended(
        application, code_interpreter_admin_router
    )
    include_router_with_global_prefix_prepended(
        application, image_generation_admin_router
    )
    include_router_with_global_prefix_prepended(application, embedding_admin_router)
    include_router_with_global_prefix_prepended(application, embedding_router)
    include_router_with_global_prefix_prepended(application, web_search_router)
    include_router_with_global_prefix_prepended(application, web_search_admin_router)
    include_router_with_global_prefix_prepended(application, tracing_admin_router)
    include_router_with_global_prefix_prepended(application, voice_admin_router)
    include_router_with_global_prefix_prepended(application, voice_router)
    include_router_with_global_prefix_prepended(application, voice_websocket_router)
    include_router_with_global_prefix_prepended(
        application, opensearch_migration_admin_router
    )
    include_router_with_global_prefix_prepended(
        application, token_rate_limit_settings_router
    )
    include_router_with_global_prefix_prepended(application, cost_override_router)
    include_router_with_global_prefix_prepended(application, user_usage_router)
    include_router_with_global_prefix_prepended(application, admin_usage_router)
    include_router_with_global_prefix_prepended(application, api_key_router)
    include_router_with_global_prefix_prepended(application, standard_oauth_router)
    include_router_with_global_prefix_prepended(application, federated_router)
    include_router_with_global_prefix_prepended(application, mcp_router)
    include_router_with_global_prefix_prepended(application, mcp_admin_router)
    include_router_with_global_prefix_prepended(application, skill_router)

    include_router_with_global_prefix_prepended(application, pat_router)
    include_router_with_global_prefix_prepended(application, captcha_router)

    # Password login is served in every deployment mode.
    include_auth_router_with_prefix(
        application,
        fastapi_users.get_auth_router(auth_backend),
        prefix="/auth",
    )

    include_auth_router_with_prefix(
        application,
        fastapi_users.get_register_router(UserRead, UserCreate),
        prefix="/auth",
    )

    include_auth_router_with_prefix(
        application,
        fastapi_users.get_reset_password_router(),
        prefix="/auth",
    )
    include_auth_router_with_prefix(
        application,
        fastapi_users.get_verify_router(UserRead),
        prefix="/auth",
    )
    include_auth_router_with_prefix(
        application,
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/users",
    )

    # Mobile bearer gateway (login/refresh/logout + the SSO code exchange).
    include_auth_router_with_prefix(
        application,
        mobile_auth_router,
        prefix="/auth/mobile",
    )

    # Env-credential Google login rides alongside provider rows when OAuth
    # credentials are configured.
    if OAUTH_ENABLED:
        google_login_scopes = list(
            GOOGLE_OAUTH_SCOPE_OVERRIDE or GOOGLE_LOGIN_BASE_SCOPES
        )

        oauth_client = GoogleOAuth2(
            OAUTH_CLIENT_ID,
            OAUTH_CLIENT_SECRET,
            scopes=google_login_scopes,
        )
        include_auth_router_with_prefix(
            application,
            create_onyx_oauth_router(
                oauth_client,
                auth_backend,
                USER_AUTH_SECRET,
                associate_by_email=True,
                is_verified_by_default=True,
                redirect_url=f"{WEB_DOMAIN}/auth/oauth/callback",
            ),
            prefix="/auth/oauth",
        )

        # Dedicated mobile Google OAuth router. redirect_url is under /api so the IdP
        # returns to the api_server, not the web callback wrapper (which drops the
        # cookie-less deep-link 302). mobile_auth_backend only namespaces its route
        # names apart from the web router's; same Google client + strategy.
        include_auth_router_with_prefix(
            application,
            create_onyx_oauth_router(
                oauth_client,
                mobile_auth_backend,
                USER_AUTH_SECRET,
                associate_by_email=True,
                is_verified_by_default=True,
                redirect_url=f"{WEB_DOMAIN}/api/auth/mobile/oauth/callback",
            ),
            prefix="/auth/mobile/oauth",
        )

    # The only SAML router. Always mounted: it resolves provider rows per request
    # (fixed and parametric authorize, one issuer-resolved callback) and rejects
    # requests when no rows exist, so it ships dark. A single-SAML deployment's row is seeded from
    # SAML_CONF_DIR at startup, so its login keeps working with no reconfig.
    include_auth_router_with_prefix(
        application,
        saml_multi_router,
    )

    # DB-backed multi-provider OIDC/Google router. Always mounted: resolves
    # provider rows per request and 404s when none exist, so it ships dark.
    include_auth_router_with_prefix(
        application,
        oidc_multi_router,
    )

    include_auth_router_with_prefix(
        application,
        fastapi_users.get_refresh_router(auth_backend),
        prefix="/auth",
    )

    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )

    application.add_exception_handler(ValueError, value_error_handler)

    if not CORS_ALLOW_CREDENTIALS:
        logger.warning(
            "CORS_ALLOWED_ORIGIN is unset or contains '*'; cross-origin "
            "requests will be served without credentials. Set "
            "CORS_ALLOWED_ORIGIN to your frontend origin(s) to allow "
            "credentialed cross-origin requests."
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGIN,  # Configurable via environment variable
        allow_credentials=CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Gate the OAuth callback on a signed captcha cookie set by the frontend
    # before the Google redirect. No-op unless is_captcha_enabled() is true
    # (requires CAPTCHA_ENABLED=true and RECAPTCHA_SECRET_KEY set).
    application.add_middleware(CaptchaCookieMiddleware)
    application.add_middleware(LoginCaptchaMiddleware)

    # Registered last so it is the outermost middleware and the client-IP
    # contextvar is set before any downstream middleware, handler, or telemetry
    # call runs. Added in place once — downstream capture sites read it via
    # ``current_client_ip()`` rather than threading the request through.
    application.add_middleware(ClientIPMiddleware)

    if LOG_ENDPOINT_LATENCY:
        add_latency_logging_middleware(application, logger)

    add_onyx_request_id_middleware(application, "API", logger)

    # Set endpoint context for per-endpoint DB pool attribution metrics.
    # Must be registered after all routes are added.
    add_endpoint_context_middleware(application)

    # HTTP request metrics (latency histograms, in-progress gauge, slow request
    # counter). Must be called here — before the app starts — because the
    # instrumentator adds middleware via app.add_middleware().
    setup_prometheus_metrics(application)

    # Ensure all routes have auth enabled or are explicitly marked as public
    check_router_auth(application)

    use_route_function_names_as_operation_ids(application)

    return application


# NOTE: needs to be outside of the `if __name__ == "__main__"` block so that the
# app is exportable
set_is_ee_based_on_env_variable()
app = fetch_versioned_implementation(module="onyx.main", attribute="get_application")


if __name__ == "__main__":
    logger.notice(
        "Starting Onyx Backend version %s on http://%s:%s/",
        __version__,
        APP_HOST,
        str(APP_PORT),
    )

    if global_version.is_ee_version():
        logger.notice("Running Enterprise Edition")

    uvicorn.run(app, host=APP_HOST, port=APP_PORT)
