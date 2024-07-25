from fastapi import FastAPI
from httpx_oauth.clients.openid import OpenID

from danswer.auth.users import auth_backend
from danswer.auth.users import fastapi_users
from danswer.configs.app_configs import AUTH_TYPE
from danswer.configs.app_configs import OAUTH_CLIENT_ID
from danswer.configs.app_configs import OAUTH_CLIENT_SECRET
from danswer.configs.app_configs import USER_AUTH_SECRET
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.configs.constants import AuthType
from danswer.main import get_application as get_application_base
from danswer.main import include_router_with_global_prefix_prepended
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import global_version
from ee.danswer.configs.app_configs import OPENID_CONFIG_URL
from ee.danswer.server.analytics.api import router as analytics_router
from ee.danswer.server.api_key.api import router as api_key_router
from ee.danswer.server.auth_check import check_ee_router_auth
from ee.danswer.server.enterprise_settings.api import (
    admin_router as enterprise_settings_admin_router,
)
from ee.danswer.server.enterprise_settings.api import (
    basic_router as enterprise_settings_router,
)
from ee.danswer.server.query_and_chat.chat_backend import (
    router as chat_router,
)
from ee.danswer.server.query_and_chat.query_backend import (
    basic_router as query_router,
)
from ee.danswer.server.query_history.api import router as query_history_router
from ee.danswer.server.reporting.usage_export_api import router as usage_export_router
from ee.danswer.server.saml import router as saml_router
from ee.danswer.server.seeding import seed_db
from ee.danswer.server.token_rate_limits.api import (
    router as token_rate_limit_settings_router,
)
from ee.danswer.server.user_group.api import router as user_group_router
from ee.danswer.utils.encryption import test_encryption

logger = setup_logger()


def get_application() -> FastAPI:
    # Anything that happens at import time is not guaranteed to be running ee-version
    # Anything after the server startup will be running ee version
    global_version.set_ee()

    test_encryption()

    application = get_application_base()

    if AUTH_TYPE == AuthType.OIDC:
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_oauth_router(
                OpenID(OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OPENID_CONFIG_URL),
                auth_backend,
                USER_AUTH_SECRET,
                associate_by_email=True,
                is_verified_by_default=True,
                redirect_url=f"{WEB_DOMAIN}/auth/oidc/callback",
            ),
            prefix="/auth/oidc",
            tags=["auth"],
        )
        # need basic auth router for `logout` endpoint
        include_router_with_global_prefix_prepended(
            application,
            fastapi_users.get_auth_router(auth_backend),
            prefix="/auth",
            tags=["auth"],
        )

    elif AUTH_TYPE == AuthType.SAML:
        include_router_with_global_prefix_prepended(application, saml_router)

    # RBAC / group access control
    include_router_with_global_prefix_prepended(application, user_group_router)
    # Analytics endpoints
    include_router_with_global_prefix_prepended(application, analytics_router)
    include_router_with_global_prefix_prepended(application, query_history_router)
    # Api key management
    include_router_with_global_prefix_prepended(application, api_key_router)
    # EE only backend APIs
    include_router_with_global_prefix_prepended(application, query_router)
    include_router_with_global_prefix_prepended(application, chat_router)
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

    # Ensure all routes have auth enabled or are explicitly marked as public
    check_ee_router_auth(application)

    # seed the Danswer environment with LLMs, Assistants, etc. based on an optional
    # environment variable. Used to automate deployment for multiple environments.
    seed_db()

    return application
