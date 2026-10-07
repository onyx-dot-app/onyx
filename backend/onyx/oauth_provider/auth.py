from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from onyx.auth.constants import (
    OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX,
    OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX,
    OAUTH_PROVIDER_SCOPE,
)
from onyx.auth.oauth_provider import OAuthProviderTokenKind, parse_oauth_provider_token
from onyx.auth.permissions import has_global_permission
from onyx.configs import app_configs
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.oauth_provider import (
    OAUTH_PROVIDER_STORAGE_ERRORS,
    oauth_provider_owner_is_member,
    oauth_provider_owner_snapshot,
    oauth_provider_tenant_has_members,
    resolve_oauth_provider_access_token,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth_provider.config import get_oauth_provider_settings
from onyx.oauth_provider.models import OAuthProviderTokenInfo
from onyx.server.middleware.api_prefix import strip_api_prefix
from shared_configs.contextvars import UsageCredentialIdentity, get_current_tenant_id
from shared_configs.enums import UsageCredentialType

_ACCESS_ROUTES = frozenset(
    {
        ("GET", "/oauth-provider/introspect"),
        ("POST", "/search"),
        ("POST", "/web-search/search-lite"),
        ("POST", "/web-search/open-urls"),
        ("GET", "/manage/indexed-sources"),
        ("GET", "/manage/document-set"),
        ("GET", "/persona"),
    }
)
_TOKEN_INFO_SCOPE_KEY = "onyx.mcp_oauth"


def _is_mcp_oauth_access_route(request: Request) -> bool:
    return (request.method, strip_api_prefix(request.url.path)) in _ACCESS_ROUTES


def extract_oauth_provider_bearer(request: Request) -> str | None:
    authorization = request.headers.getlist("authorization")
    alternate = request.headers.getlist("x-onyx-authorization")
    values = authorization + alternate
    if not any(
        part.startswith(
            (OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX, OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX)
        )
        for value in values
        for part in value.split()
    ):
        return None
    if len(authorization) > 1 or len(alternate) > 1:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    credentials = [value.split() for value in values]
    if any(len(parts) != 2 or parts[0].lower() != "bearer" for parts in credentials):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    tokens = {parts[1] for parts in credentials}
    if len(tokens) != 1:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    return tokens.pop()


async def oauth_provider_tenant_from_request(request: Request) -> str | None:
    raw_token = extract_oauth_provider_bearer(request)
    if raw_token is None:
        return None
    parsed = parse_oauth_provider_token(raw_token)
    if (
        not app_configs.OAUTH_PROVIDER_ENABLED
        or parsed is None
        or parsed.kind != OAuthProviderTokenKind.ACCESS
    ):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    if not _is_mcp_oauth_access_route(request):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    try:
        known = await run_in_threadpool(
            oauth_provider_tenant_has_members, parsed.tenant_id
        )
    except OAUTH_PROVIDER_STORAGE_ERRORS as error:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE) from error
    if not known:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    return parsed.tenant_id


def get_oauth_provider_token_info(request: Request) -> OAuthProviderTokenInfo | None:
    info = request.scope.get(_TOKEN_INFO_SCOPE_KEY)
    return info if isinstance(info, OAuthProviderTokenInfo) else None


async def authenticate_oauth_provider_request(
    request: Request, session: AsyncSession, raw_token: str
) -> User:
    if not app_configs.OAUTH_PROVIDER_ENABLED:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    if not _is_mcp_oauth_access_route(request):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    try:
        result = await resolve_oauth_provider_access_token(
            session, raw_token, resource=get_oauth_provider_settings().mcp_resource_url
        )
        if result is None:
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
        user, info = result
        owner = oauth_provider_owner_snapshot(user)
        await session.commit()
        is_member = await run_in_threadpool(
            oauth_provider_owner_is_member,
            get_current_tenant_id(),
            owner.email,
            owner.oauth_identities,
        )
    except OAUTH_PROVIDER_STORAGE_ERRORS as error:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE) from error
    if not is_member:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    if set(info.grant.scopes) != {OAUTH_PROVIDER_SCOPE} or not has_global_permission(
        user, Permission.READ_SEARCH
    ):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    request.state.token_scopes = [Permission.READ_SEARCH]
    request.state.usage_credential = UsageCredentialIdentity(
        UsageCredentialType.OAUTH_PROVIDER,
        str(info.grant.id),
        info.grant.client_name,
    )
    request.scope[_TOKEN_INFO_SCOPE_KEY] = info
    return user
