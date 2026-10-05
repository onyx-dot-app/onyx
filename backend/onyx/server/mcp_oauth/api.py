import hashlib
import json
import time
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from mcp.server.auth.provider import construct_redirect_uri
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.auth.schemas import AuthBackend
from onyx.auth.users import current_limited_user, get_jwt_strategy
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType, Permission
from onyx.db.mcp_oauth import (
    MCP_OAUTH_STORAGE_ERRORS,
    list_mcp_oauth_grants,
    mcp_oauth_owner_is_member,
    mcp_oauth_owner_snapshot,
    revoke_mcp_oauth_grant__no_commit,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.mcp_oauth.attempts import (
    AUTHORIZATION_CODE_TTL_SECONDS,
    bind_authorization_request,
    consume_authorization_request,
    get_authorization_request,
    store_authorization_code,
)
from onyx.mcp_oauth.auth import get_mcp_oauth_token_info
from onyx.mcp_oauth.config import get_mcp_oauth_settings
from onyx.mcp_oauth.models import (
    MCPOAuthGrantInfo,
    MCPOAuthIntrospection,
    StoredMCPOAuthCode,
)
from onyx.server.mcp_oauth.provider import OnyxMCPOAuthProvider
from onyx.server.settings.store import load_settings
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import UsageCredentialIdentity, get_current_tenant_id
from shared_configs.enums import UsageCredentialType


def _require_enabled() -> None:
    if not app_configs.MCP_SERVER_OAUTH_ENABLED:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)


router = APIRouter(prefix="/mcp-oauth", dependencies=[Depends(_require_enabled)])


class MCPOAuthConsentInfo(BaseModel):
    client_name: str
    redirect_origin: str
    account_email: str
    workspace_name: str
    scopes: list[str]
    csrf_token: str = Field(repr=False)


class MCPOAuthConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", max_length=43)
    csrf_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", max_length=43, repr=False)
    decision: Literal["allow", "deny"]


class MCPOAuthConsentResult(BaseModel):
    redirect_url: str


def _session_hash(request: Request, user: User) -> str:
    state = request.scope.get("state", {})
    credential = state.get("usage_credential")
    if (
        user.account_type != AccountType.STANDARD
        or not isinstance(credential, UsageCredentialIdentity)
        or credential.credential_type
        not in {UsageCredentialType.SESSION, UsageCredentialType.JWT}
        # JWT passthrough does not bind the request to a tenant.
        or (MULTI_TENANT and credential.credential_type == UsageCredentialType.JWT)
    ):
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED, "Sign in to manage MCP connections"
        )
    cookie = request.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
    authorization = request.headers.get("Authorization")
    if not cookie and not authorization:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    cookie_identity: str | tuple[str, str] | None = cookie
    authorization_identity: str | tuple[str, str] | None = authorization
    if (
        app_configs.AUTH_BACKEND == AuthBackend.JWT
        and credential.credential_type == UsageCredentialType.SESSION
    ):
        token = state.get("authenticated_session_token")
        if not isinstance(token, str) or not token:
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
        session_id = get_jwt_strategy().get_session_id(token, user)
        if session_id is None:
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
        if cookie == token:
            cookie_identity = ("jwt-session", session_id)
        elif authorization is not None:
            scheme, _, bearer = authorization.partition(" ")
            if scheme.lower() != "bearer" or bearer != token:
                raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
            authorization_identity = ("jwt-session", session_id)
        else:
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    credentials = json.dumps(
        [cookie_identity, authorization_identity], separators=(",", ":")
    )
    return hashlib.sha256(credentials.encode("utf-8")).hexdigest()


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


async def _authorization_session(request: Request, user: User) -> str:
    session_hash = _session_hash(request, user)
    if not has_global_permission(user, Permission.READ_SEARCH):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    owner = mcp_oauth_owner_snapshot(user)
    try:
        member = await run_in_threadpool(
            mcp_oauth_owner_is_member,
            get_current_tenant_id(),
            owner.email,
            owner.oauth_identities,
        )
    except MCP_OAUTH_STORAGE_ERRORS as error:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE) from error
    if not member:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED, "Workspace membership is no longer active"
        )
    return session_hash


@router.get("/introspect")
def introspect(
    request: Request,
    response: Response,
    user: User = Depends(require_permission(Permission.READ_SEARCH)),
) -> MCPOAuthIntrospection:
    info = get_mcp_oauth_token_info(request)
    if info is None:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    _no_store(response)
    return MCPOAuthIntrospection(
        client_id=info.grant.client_id,
        scopes=list(info.grant.scopes),
        resource=info.grant.resource,
        expires_at=int(info.expires_at.timestamp()),
        subject=str(user.id),
        grant_id=info.grant.id,
    )


@router.get("/consent")
async def consent_details(
    request: Request,
    response: Response,
    authorization_request: str = Query(
        alias="request", pattern=r"^[A-Za-z0-9_-]{43}$", max_length=43
    ),
    user: User = Depends(require_permission(Permission.CREATE_USER_API_KEYS)),
) -> MCPOAuthConsentInfo:
    session_hash = await _authorization_session(request, user)
    pending = await get_authorization_request(authorization_request)
    if pending is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Authorization request expired")
    binding = await bind_authorization_request(
        authorization_request,
        user_id=user.id,
        tenant_id=get_current_tenant_id(),
        session_hash=session_hash,
    )
    if binding is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Restart authorization after changing accounts or workspaces",
        )
    settings = await run_in_threadpool(load_settings)
    destination = urlsplit(str(pending.params.redirect_uri))
    _no_store(response)
    return MCPOAuthConsentInfo(
        client_name=pending.client_name,
        redirect_origin=f"{destination.scheme}://{destination.netloc}",
        account_email=user.email,
        workspace_name=settings.company_name
        or urlsplit(get_mcp_oauth_settings().web_url).netloc,
        scopes=pending.params.scopes or [],
        csrf_token=binding.csrf_token,
    )


@router.post("/consent")
async def decide_consent(
    payload: MCPOAuthConsentDecision,
    request: Request,
    response: Response,
    user: User = Depends(require_permission(Permission.CREATE_USER_API_KEYS)),
) -> MCPOAuthConsentResult:
    settings = get_mcp_oauth_settings()
    if request.headers.get("origin") != settings.web_origin:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Invalid authorization origin")
    session_hash = await _authorization_session(request, user)
    pending = await consume_authorization_request(
        payload.request_id,
        user_id=user.id,
        tenant_id=get_current_tenant_id(),
        session_hash=session_hash,
        csrf_token=payload.csrf_token,
    )
    if pending is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Invalid or expired authorization request"
        )
    _no_store(response)
    if payload.decision == "deny":
        return MCPOAuthConsentResult(
            redirect_url=construct_redirect_uri(
                str(pending.params.redirect_uri),
                error="access_denied",
                state=pending.params.state,
                iss=settings.issuer_url,
            )
        )
    client = await OnyxMCPOAuthProvider(settings).get_client(pending.client_id)
    if client is None or pending.params.resource != settings.resource_url:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Client authorization is no longer available"
        )
    try:
        client.validate_redirect_uri(pending.params.redirect_uri)
    except InvalidRedirectUriError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Client redirect changed; restart authorization",
        ) from error
    code = await store_authorization_code(
        StoredMCPOAuthCode(
            authorization=pending,
            user_id=user.id,
            tenant_id=get_current_tenant_id(),
            expires_at=time.time() + AUTHORIZATION_CODE_TTL_SECONDS,
        )
    )
    return MCPOAuthConsentResult(
        redirect_url=construct_redirect_uri(
            str(pending.params.redirect_uri),
            code=code,
            state=pending.params.state,
            iss=settings.issuer_url,
        )
    )


@router.get("/grants")
def connected_clients(
    request: Request,
    response: Response,
    user: User = Depends(current_limited_user),
) -> list[MCPOAuthGrantInfo]:
    _session_hash(request, user)
    _no_store(response)
    with get_session_with_current_tenant() as session:
        return list_mcp_oauth_grants(session, user.id)


@router.delete("/grants/{grant_id}")
def disconnect_client(
    grant_id: UUID,
    request: Request,
    response: Response,
    user: User = Depends(current_limited_user),
) -> dict[str, bool]:
    _session_hash(request, user)
    if request.headers.get("origin") != get_mcp_oauth_settings().web_origin:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Invalid authorization origin")
    with get_session_with_current_tenant() as session:
        revoked = revoke_mcp_oauth_grant__no_commit(
            session, grant_id=grant_id, user_id=user.id
        )
        session.commit()
    if not revoked:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    _no_store(response)
    return {"revoked": True}
