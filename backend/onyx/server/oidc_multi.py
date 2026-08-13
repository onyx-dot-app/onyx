"""Per-request-resolved multi-provider OAuth2/OIDC login.

Resolves the enabled provider row from the database on each request so one
deployment can serve multiple Google and generic OIDC IdPs. Ships dark when no
matching provider rows exist.

Provider rows are per-workspace, and on cloud a login request carries no session
to resolve the workspace from. Both halves of the flow therefore name it
explicitly: authorize takes the signed pin discovery issued, and the callback
reads it back out of the OAuth state Onyx signed on the way out.
"""

import hashlib
import json
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi_users.authentication import Strategy
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.openid import BASE_SCOPES
from httpx_oauth.oauth2 import BaseOAuth2, GetAccessTokenError
from sqlalchemy.orm import Session

from onyx.auth.oidc_client import VerifiedEmailOpenID
from onyx.auth.sso_tenant_token import (
    SSO_TENANT_TOKEN_PARAM,
    decode_sso_tenant_token,
)
from onyx.auth.sso_url_guard import (
    UnsafeSSOUrl,
    validate_discovered_endpoints,
    validate_idp_url,
)
from onyx.auth.sso_web_error import delete_pkce_cookie, redirect_sso_errors_to_web
from onyx.auth.users import (
    CSRF_TOKEN_COOKIE_NAME,
    CSRF_TOKEN_KEY,
    STATE_TOKEN_LIFETIME_SECONDS,
    OAuth2AuthorizeResponse,
    UserManager,
    auth_backend,
    complete_login_flow,
    decode_and_validate_oauth_state,
    generate_csrf_token,
    generate_pkce_pair,
    generate_state_token,
    get_pkce_cookie_name,
    get_user_manager,
)
from onyx.configs.app_configs import (
    GOOGLE_LOGIN_BASE_SCOPES,
    GOOGLE_OAUTH_SCOPE_OVERRIDE,
    OIDC_PKCE_ENABLED,
    OIDC_SCOPE_OVERRIDE,
    USER_AUTH_SECRET,
    WEB_DOMAIN,
)
from onyx.db.engine.sql_engine import (
    get_session_with_current_tenant,
    get_session_with_tenant,
)
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider, User
from onyx.db.sso_provider import (
    fetch_sso_provider_by_name,
    sso_login_callback_uri,
    validate_sso_config,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.url import sanitize_next_url
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    SESSION_TENANT_OVERRIDE_CONTEXTVAR,
    get_current_tenant_id,
)

router = APIRouter(prefix="/auth/oidc")

_NO_WORKSPACE_DETAIL = (
    "Sign-in did not identify a workspace. Return to the login page and enter "
    "your email to continue."
)

# Named in the OAuth state so the callback can reach the workspace whose
# provider row started the flow.
_STATE_TENANT_KEY = "tenant_id"

_CLIENT_CACHE_TTL_SECONDS = 600
# Hardcoded off: linking a second IdP to an existing account by verified email is
# an account-takeover vector when two IdPs can assert one domain.
_ALLOW_AUTO_LINK = False

_CLIENT_CACHE: TTLCache[tuple[str, str, SSOProviderType, str], BaseOAuth2[Any]] = (
    TTLCache(maxsize=128, ttl=_CLIENT_CACHE_TTL_SECONDS)
)
_COOKIE_SECURE = WEB_DOMAIN.startswith("https")


@contextmanager
def _workspace_session(tenant_id: str | None) -> Generator[Session, None, None]:
    # Context var travels with the session so downstream login code agrees on
    # the workspace this request belongs to.
    if not MULTI_TENANT:
        with get_session_with_current_tenant() as db_session:
            yield db_session
        return

    if not tenant_id:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, _NO_WORKSPACE_DETAIL)
    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            yield db_session
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)


@contextmanager
def _pinned_workspace(tenant_id: str | None) -> Generator[None, None, None]:
    """Bind the callback's whole tail to one workspace. The override is what
    keeps a pinned login there: session issuance and post-register read it
    instead of re-deriving from the address."""
    if not MULTI_TENANT:
        yield
        return
    if not tenant_id:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, _NO_WORKSPACE_DETAIL)
    tenant_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    override_token = SESSION_TENANT_OVERRIDE_CONTEXTVAR.set(tenant_id)
    try:
        yield
    finally:
        SESSION_TENANT_OVERRIDE_CONTEXTVAR.reset(override_token)
        CURRENT_TENANT_ID_CONTEXTVAR.reset(tenant_token)


async def get_authorize_session(
    request: Request,
) -> AsyncGenerator[Session, None]:
    """Session for the authorize call, which has no session cookie to resolve a
    workspace from and instead presents the pin discovery issued."""
    workspace_token = request.query_params.get(SSO_TENANT_TOKEN_PARAM)
    tenant_id = decode_sso_tenant_token(workspace_token) if workspace_token else None
    with _workspace_session(tenant_id) as db_session:
        yield db_session


def _state_workspace(state_data: dict[str, Any]) -> str | None:
    tenant_id = state_data.get(_STATE_TENANT_KEY)
    return tenant_id if isinstance(tenant_id, str) and tenant_id else None


def _resolve_oidc_provider(
    db_session: Session, provider_name: str
) -> tuple[SSOProvider, dict[str, Any]]:
    provider = fetch_sso_provider_by_name(
        db_session=db_session,
        name=provider_name,
        enabled_only=True,
    )
    if provider is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")
    if provider.provider_type not in (
        SSOProviderType.GOOGLE_OAUTH,
        SSOProviderType.OIDC,
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")
    if provider.config is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")

    raw_config = provider.config.get_value(apply_mask=False)
    try:
        config = validate_sso_config(provider.provider_type, raw_config)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider") from e
    return provider, config


def _pkce_enabled(config: dict[str, Any]) -> bool:
    """PKCE is on when the provider row enables it. The deployment-wide env
    flag can still force it on while that flag exists."""
    return bool(config.get("pkce_enabled")) or OIDC_PKCE_ENABLED


def _drop_unadvertised_offline_access(client: BaseOAuth2[Any]) -> None:
    """Some IdPs (e.g. Amazon Cognito) fail the entire authorize request on
    scopes they don't support, so the auto-added offline_access scope only
    survives when the discovery doc advertises it. A discovery doc without
    scopes_supported keeps the scope, since support can't be ruled out."""
    discovery = getattr(client, "openid_configuration", None) or {}
    supported = discovery.get("scopes_supported")
    if supported is None or "offline_access" in supported:
        return
    client.base_scopes = [
        scope for scope in (client.base_scopes or []) if scope != "offline_access"
    ]


def _build_client(provider: SSOProvider, config: dict[str, Any]) -> BaseOAuth2[Any]:
    if provider.provider_type is SSOProviderType.OIDC:
        # Re-checked here, not just on write, so a row stored before the guard
        # existed cannot be fetched either. Cached with the client, so this
        # costs one resolution per TTL rather than one per login.
        validate_idp_url(config["openid_config_url"], field="openid_config_url")
        # Scope overrides let providers request extra API scopes (e.g. MS Graph
        # User.Read for claims capture): the row's scopes win, then the env
        # override while it exists. offline_access secures refresh tokens.
        scopes = list(config.get("scopes") or OIDC_SCOPE_OVERRIDE or BASE_SCOPES)
        offline_access_auto_added = "offline_access" not in scopes
        if offline_access_auto_added:
            scopes.append("offline_access")
        client = VerifiedEmailOpenID(
            config["client_id"],
            config["client_secret"],
            config["openid_config_url"],
            name=provider.name,
            base_scopes=scopes,
            require_verified_email=config.get("require_verified_email", False),
        )
        # The document is attacker-chosen once its URL is, and the endpoints it
        # names are fetched next, so they get the same treatment as the URL.
        validate_discovered_endpoints(getattr(client, "openid_configuration", None))
        # Explicitly configured offline_access is always respected as-is.
        if offline_access_auto_added:
            _drop_unadvertised_offline_access(client)
        return client
    if provider.provider_type is SSOProviderType.GOOGLE_OAUTH:
        return GoogleOAuth2(
            config["client_id"],
            config["client_secret"],
            scopes=list(
                config.get("scopes")
                or GOOGLE_OAUTH_SCOPE_OVERRIDE
                or GOOGLE_LOGIN_BASE_SCOPES
            ),
            name=provider.name,
        )

    raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")


def _get_cache_key(
    provider: SSOProvider, config: dict[str, Any]
) -> tuple[str, str, SSOProviderType, str]:
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).hexdigest()
    # Tenant-scope the key so two tenants with a same-named provider never share
    # a client.
    return get_current_tenant_id(), provider.name, provider.provider_type, config_hash


async def _get_oauth_client(
    provider: SSOProvider, config: dict[str, Any]
) -> BaseOAuth2[Any]:
    # Building an OIDC client fetches the IdP discovery doc over the network, so
    # cache per provider+config (Google clients share the cache, no fetch). The
    # TTL bounds how long stale IdP discovery data lives before a rebuild.
    cache_key = _get_cache_key(provider, config)
    cached_client = _CLIENT_CACHE.get(cache_key)
    if cached_client is not None:
        return cached_client

    try:
        client = await run_in_threadpool(_build_client, provider, config)
    except UnsafeSSOUrl as e:
        # A row stored before the write guard, or a discovery doc that started
        # naming a rejected endpoint, reaches this browser-facing path. Surface a
        # clean error rather than letting the ValueError escape as a raw 400.
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "This provider's sign-in URL is not reachable.",
        ) from e
    _CLIENT_CACHE[cache_key] = client
    return client


def _set_oauth_cookie(
    response: Response,
    *,
    key: str,
    value: str,
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=STATE_TOKEN_LIFETIME_SECONDS,
        path="/",
        secure=_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _callback_uri(provider: SSOProvider, config: dict[str, Any]) -> str:
    # Legacy-callback rows land on the web wrappers at the legacy paths, which
    # forward to this router. The fixed /callback below resolves the row from
    # the signed state.
    return sso_login_callback_uri(provider, config, WEB_DOMAIN)


@router.get("/{provider_name}/authorize")
async def oidc_login_for_provider(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_authorize_session),
) -> Response:
    provider, config = _resolve_oidc_provider(db_session, provider_name)
    client = await _get_oauth_client(provider, config)
    redirect_uri = _callback_uri(provider, config)
    next_url = sanitize_next_url(request.query_params.get("next"))
    csrf_token = generate_csrf_token()
    use_pkce = _pkce_enabled(config)
    state = generate_state_token(
        {
            "next_url": next_url,
            "provider_name": provider_name,
            # Pins this flow's PKCE mode, so a provider edit mid-login cannot
            # make the callback disagree with the authorization request.
            "pkce": use_pkce,
            # The IdP redirect arrives with no session, so the state is the only
            # thing carrying the workspace across the round trip.
            _STATE_TENANT_KEY: get_current_tenant_id(),
            CSRF_TOKEN_KEY: csrf_token,
        },
        USER_AUTH_SECRET,
    )

    extras: dict[str, str] | None = None
    if provider.provider_type is SSOProviderType.GOOGLE_OAUTH:
        extras = {"access_type": "offline", "prompt": "consent"}

    code_verifier: str | None = None
    if use_pkce:
        code_verifier, code_challenge = generate_pkce_pair()
        authorization_url = await client.get_authorization_url(
            redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            extras_params=extras,
        )
    else:
        authorization_url = await client.get_authorization_url(
            redirect_uri,
            state=state,
            extras_params=extras,
        )

    response = JSONResponse(
        content=OAuth2AuthorizeResponse(
            authorization_url=authorization_url
        ).model_dump()
    )
    _set_oauth_cookie(
        response,
        key=CSRF_TOKEN_COOKIE_NAME,
        value=csrf_token,
    )
    if code_verifier is not None:
        _set_oauth_cookie(
            response,
            key=get_pkce_cookie_name(state),
            value=code_verifier,
        )

    return response


@router.get("/callback")
@redirect_sso_errors_to_web
async def oidc_login_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    """Fixed callback for rows whose IdP client allowlists a legacy redirect
    URI. The row is resolved from the signed state, the same per-request
    routing the SAML callback does with issuers."""
    if state is None:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Missing state parameter in OAuth callback",
        )
    state_data = decode_and_validate_oauth_state(
        request=request,
        state_value=state,
        state_secret=USER_AUTH_SECRET,
    )
    provider_name = state_data.get("provider_name")
    if not provider_name:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "OAuth state does not identify a provider",
        )
    return await oidc_login_callback_for_provider(
        provider_name=provider_name,
        request=request,
        code=code,
        state=state,
        error=error,
        strategy=strategy,
        user_manager=user_manager,
    )


@router.get("/{provider_name}/callback")
@redirect_sso_errors_to_web
async def oidc_login_callback_for_provider(
    provider_name: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    if error is not None:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Authorization request failed or was denied",
        )
    if code is None:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Missing authorization code in OAuth callback",
        )
    if state is None:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Missing state parameter in OAuth callback",
        )

    # Validated before the workspace is read out of it, so a tampered or expired
    # state is rejected here before any workspace is selected.
    state_data = decode_and_validate_oauth_state(
        request=request,
        state_value=state,
        state_secret=USER_AUTH_SECRET,
        expected_provider_name=provider_name,
    )
    pinned_tenant_id = _state_workspace(state_data)

    # Everything below runs inside the pinned workspace: the client cache is
    # keyed on the current tenant, and session issuance reads the override.
    with _pinned_workspace(pinned_tenant_id):
        with get_session_with_current_tenant() as db_session:
            provider, config = _resolve_oidc_provider(db_session, provider_name)
            client = await _get_oauth_client(provider, config)
            redirect_uri = _callback_uri(provider, config)
            allowed_email_domains = list(provider.allowed_email_domains)

        # The state pins the flow's PKCE mode. States without the claim fall
        # back to the row's setting so logins in flight across a deploy complete.
        use_pkce = (
            bool(state_data["pkce"]) if "pkce" in state_data else _pkce_enabled(config)
        )
        code_verifier: str | None = None
        if use_pkce:
            code_verifier = request.cookies.get(get_pkce_cookie_name(state))
            if not code_verifier:
                raise OnyxError(
                    OnyxErrorCode.VALIDATION_ERROR,
                    "Missing PKCE verifier cookie in OAuth callback",
                )

        try:
            token = await client.get_access_token(code, redirect_uri, code_verifier)
        except GetAccessTokenError as e:
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "Authorization code exchange failed",
            ) from e

        redirect_response = await complete_login_flow(
            oauth_client=client,
            token=token,
            state_data=state_data,
            request=request,
            user_manager=user_manager,
            backend=auth_backend,
            strategy=strategy,
            associate_by_email=_ALLOW_AUTO_LINK,
            is_verified_by_default=True,
            allowed_email_domains_override=allowed_email_domains,
        )

    if use_pkce:
        delete_pkce_cookie(redirect_response, state)

    return redirect_response
