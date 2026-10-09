"""Workspace discovery for the cloud login page.

Cloud serves every workspace from one domain, so the login page cannot know
which IdP to offer until the visitor names themselves. This endpoint takes an
address, resolves the workspace from the shared catalog, and returns that
workspace's sign-in buttons with a signed pin the authorize call uses to reach
the right schema.

The response is deliberately uniform: an address that maps nowhere, maps to
several workspaces, or maps to a workspace with no SSO all return an empty
list, so the endpoint cannot be used to tell those cases apart.
"""

import time

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr

from onyx.auth.sso_tenant_token import (
    SSO_TENANT_TOKEN_PARAM,
    generate_sso_tenant_token,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import SSOProvider
from onyx.db.sso_provider import (
    fetch_sso_providers,
    sso_authorize_path,
    sso_provider_type_supported,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.manage.models import SSOProviderOption
from onyx.utils.client_ip import get_client_ip
from onyx.utils.logger import setup_logger
from onyx.utils.url import add_url_params
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()

router = APIRouter(prefix="/auth/sso")

# A whole office shares one public address, so this has to clear a company
# signing in on a Monday morning while still bounding a script walking an
# address list. It bounds the rate of enumeration, not the possibility.
_PER_IP_PER_HOUR = 300
_BUCKET_SECONDS = 3600
_REDIS_KEY_PREFIX = "sso_discovery_rate:"


class SSODiscoveryRequest(BaseModel):
    email: EmailStr


class SSODiscoveryResponse(BaseModel):
    providers: list[SSOProviderOption]


async def _enforce_discovery_rate_limit(request: Request) -> None:
    # Single-tenant has one workspace to enumerate and runs without Redis on
    # Onyx-lite, so the bound applies only on cloud, where it is the sole limit
    # on address enumeration.
    if not MULTI_TENANT:
        return

    ip = get_client_ip(request) or "unknown"
    key = f"{_REDIS_KEY_PREFIX}{ip}:{int(time.time() // _BUCKET_SECONDS)}"
    try:
        redis = await get_async_redis_connection()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _BUCKET_SECONDS)
        incr_result, _ = await pipe.execute()
        count = int(incr_result)
    except Exception as e:
        # Fails closed. This endpoint answers about addresses it has not
        # authenticated, so losing Redis must cost the lookup, not the probing
        # bound on it.
        logger.exception("SSO discovery rate-limit unavailable, refusing lookup")
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "Sign-in lookup is briefly unavailable. Use Google or your password.",
        ) from e

    if count > _PER_IP_PER_HOUR:
        logger.warning(
            "SSO discovery rate limit exceeded for ip=%s count=%s", ip, count
        )
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "Too many sign-in lookups from this network. Please wait before trying again.",
        )


def _authorize_url(provider: SSOProvider, workspace_token: str | None) -> str:
    path = sso_authorize_path(provider)
    if workspace_token is None:
        return path
    return add_url_params(path, {SSO_TENANT_TOKEN_PARAM: workspace_token})


def _login_options(
    tenant_id: str, workspace_token: str | None
) -> list[SSOProviderOption]:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        return [
            SSOProviderOption(
                name=provider.name,
                display_name=provider.display_name,
                provider_type=provider.provider_type,
                authorize_url=_authorize_url(provider, workspace_token),
            )
            for provider in fetch_sso_providers(db_session, enabled_only=True)
            if sso_provider_type_supported(provider.provider_type)
        ]


def _resolve_workspace(email: str) -> str | None:
    """An existing membership wins: an invited or returning user reaches the
    workspace they actually belong to, even if their address domain routes
    elsewhere. Domain routing is the fallback that lets a first-time user with no
    membership reach a workspace at all."""
    tenant_id = fetch_ee_implementation_or_noop(
        "onyx.db.user_tenant_mapping", "lookup_tenant_id_for_login", None
    )(email)
    if tenant_id:
        return tenant_id

    return fetch_ee_implementation_or_noop(
        "onyx.db.tenant_sso_domain", "lookup_tenant_id_for_email_domain", None
    )(email)


def _discover(email: str) -> list[SSOProviderOption]:
    if not MULTI_TENANT:
        return _login_options(POSTGRES_DEFAULT_SCHEMA, workspace_token=None)

    tenant_id = _resolve_workspace(email)
    if not tenant_id or tenant_id == POSTGRES_DEFAULT_SCHEMA:
        return []

    return _login_options(tenant_id, generate_sso_tenant_token(tenant_id))


@router.post("/discover")
async def discover_sso_providers(
    payload: SSODiscoveryRequest, request: Request
) -> SSODiscoveryResponse:
    await _enforce_discovery_rate_limit(request)
    providers = await run_in_threadpool(_discover, payload.email)
    return SSODiscoveryResponse(providers=providers)
