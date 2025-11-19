from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx_oauth.clients.google import GoogleOAuth2

from ee.onyx.server.analytics.api import router as analytics_router
from ee.onyx.server.auth_check import check_ee_router_auth
from ee.onyx.server.documents.cc_pair import router as ee_document_cc_pair_router
from ee.onyx.server.enterprise_settings.api import (
    admin_router as enterprise_settings_admin_router,
)
from ee.onyx.server.enterprise_settings.api import (
    basic_router as enterprise_settings_router,
)
from ee.onyx.server.evals.api import router as evals_router
from ee.onyx.server.manage.standard_answer import router as standard_answer_router
from ee.onyx.server.middleware.tenant_tracking import (
    add_api_server_tenant_id_middleware,
)
from ee.onyx.server.oauth.api import router as ee_oauth_router
from ee.onyx.server.query_and_chat.chat_backend import (
    router as chat_router,
)
from ee.onyx.server.query_and_chat.query_backend import (
    basic_router as query_router,
)
from ee.onyx.server.query_history.api import router as query_history_router
from ee.onyx.server.reporting.usage_export_api import router as usage_export_router
from ee.onyx.server.seeding import seed_db
from ee.onyx.server.tenants.api import router as tenants_router
from ee.onyx.server.token_rate_limits.api import (
    router as token_rate_limit_settings_router,
)
from ee.onyx.server.user_group.api import router as user_group_router
from ee.onyx.utils.encryption import test_encryption
from onyx.auth.users import auth_backend
from onyx.auth.users import create_onyx_oauth_router
from onyx.auth.users import fastapi_users
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import OAUTH_CLIENT_ID
from onyx.configs.app_configs import OAUTH_CLIENT_SECRET
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import AuthType
from onyx.main import get_application as get_application_base
from onyx.main import include_auth_router_with_prefix
from onyx.main import include_router_with_global_prefix_prepended
from onyx.main import lifespan as lifespan_base
from onyx.main import use_route_function_names_as_operation_ids
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Small wrapper around the lifespan of the MIT application.
    Basically just calls the base lifespan, and then adds EE-only
    steps after."""

    async with lifespan_base(app):
        # seed the Onyx environment with LLMs, Assistants, etc. based on an optional
        # environment variable. Used to automate deployment for multiple environments.
        seed_db()

        yield


def get_application() -> FastAPI:
    # Anything that happens at import time is not guaranteed to be running ee-version
    # Anything after the server startup will be running ee version
    global_version.set_ee()

    test_encryption()

    application = get_application_base(lifespan_override=lifespan)

    if MULTI_TENANT:
        add_api_server_tenant_id_middleware(application, logger)

    if AUTH_TYPE == AuthType.CLOUD:
        # For Google OAuth, refresh tokens are requested by:
        # 1. Adding the right scopes
        # 2. Properly configuring OAuth in Google Cloud Console to allow offline access
        oauth_client = GoogleOAuth2(
            OAUTH_CLIENT_ID,
            OAUTH_CLIENT_SECRET,
            # Use standard scopes that include profile and email
            scopes=["openid", "email", "profile"],
        )
        include_auth_router_with_prefix(
            application,
            create_onyx_oauth_router(
                oauth_client,
                auth_backend,
                USER_AUTH_SECRET,
                associate_by_email=True,
                is_verified_by_default=True,
                # Points the user back to the login page
                redirect_url=f"{WEB_DOMAIN}/auth/oauth/callback",
            ),
            prefix="/auth/oauth",
        )

        # Need basic auth router for `logout` endpoint
        include_auth_router_with_prefix(
            application,
            fastapi_users.get_logout_router(auth_backend),
            prefix="/auth",
        )

    # RBAC / group access control
    include_router_with_global_prefix_prepended(application, user_group_router)
    # Analytics endpoints
    include_router_with_global_prefix_prepended(application, analytics_router)
    include_router_with_global_prefix_prepended(application, query_history_router)
    # EE only backend APIs
    include_router_with_global_prefix_prepended(application, query_router)
    include_router_with_global_prefix_prepended(application, chat_router)
    include_router_with_global_prefix_prepended(application, standard_answer_router)
    include_router_with_global_prefix_prepended(application, ee_oauth_router)
    include_router_with_global_prefix_prepended(application, ee_document_cc_pair_router)
    include_router_with_global_prefix_prepended(application, evals_router)

    # Enterprise-only global settings
    include_router_with_global_prefix_prepended(
        application, enterprise_settings_admin_router
    )
    # Token rate limit settings
    include_router_with_global_prefix_prepended(
        application, token_rate_limit_settings_router
    )
    include_router_with_global_prefix_prepended(application, enterprise_settings_router)
    include_router_with_global_prefix_prepended(application, usage_export_router)

    if MULTI_TENANT:
        # Tenant management
        include_router_with_global_prefix_prepended(application, tenants_router)

    # Ensure all routes have auth enabled or are explicitly marked as public
    check_ee_router_auth(application)

    # for debugging discovered routes
    # for route in application.router.routes:
    #     print(f"Path: {route.path}, Methods: {route.methods}")

    use_route_function_names_as_operation_ids(application)

    return application
