"""Per-request-resolved multi-provider OAuth2/OIDC login.

Resolves the enabled provider row from the database on each request so one
deployment can serve multiple Google and generic OIDC IdPs. Ships dark when no
matching provider rows exist.
"""

import hashlib
import json
import secrets
import time
import uuid
from typing import Any

import jwt
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi_users.authentication import Strategy
from fastapi_users.jwt import decode_jwt
from fastapi_users.router.common import ErrorCode
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.openid import BASE_SCOPES
from httpx_oauth.oauth2 import BaseOAuth2
from httpx_oauth.oauth2 import GetAccessTokenError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth.oidc_client import VerifiedEmailOpenID
from onyx.auth.users import auth_backend
from onyx.auth.users import complete_login_flow
from onyx.auth.users import CSRF_TOKEN_COOKIE_NAME
from onyx.auth.users import CSRF_TOKEN_KEY
from onyx.auth.users import generate_csrf_token
from onyx.auth.users import generate_pkce_pair
from onyx.auth.users import generate_state_token
from onyx.auth.users import get_pkce_cookie_name
from onyx.auth.users import get_user_manager
from onyx.auth.users import OAuth2AuthorizeResponse
from onyx.auth.users import STATE_TOKEN_AUDIENCE
from onyx.auth.users import STATE_TOKEN_LIFETIME_SECONDS
from onyx.auth.users import UserManager
from onyx.configs.app_configs import GOOGLE_LOGIN_BASE_SCOPES
from onyx.configs.app_configs import OIDC_PKCE_ENABLED
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.models import User
from onyx.db.sso_provider import fetch_sso_provider_by_name
from onyx.db.sso_provider import GoogleProviderConfig
from onyx.db.sso_provider import OIDCProviderConfig
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.utils.url import sanitize_next_url

logger = setup_logger()
router = APIRouter(prefix="/auth/oidc")

_CLIENT_CACHE_TTL_SECONDS = 600
# Link a second provider to an existing account by verified email. Same-domain
# deployments (two IdPs sharing an email domain) must run this off.
_ALLOW_AUTO_LINK = True

_CLIENT_CACHE: dict[
    tuple[str, SSOProviderType, str],
    tuple[BaseOAuth2[Any], float],
] = {}


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
    if (
        provider.provider_type is not SSOProviderType.GOOGLE_OAUTH
        and provider.provider_type is not SSOProviderType.OIDC
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")
    if provider.config is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")

    raw_config = provider.config.get_value(apply_mask=False)
    try:
        if provider.provider_type is SSOProviderType.GOOGLE_OAUTH:
            return provider, GoogleProviderConfig.model_validate(
                raw_config
            ).model_dump()
        return provider, OIDCProviderConfig.model_validate(raw_config).model_dump()
    except ValidationError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider") from e


def _build_client(provider: SSOProvider, config: dict[str, Any]) -> BaseOAuth2[Any]:
    if provider.provider_type is SSOProviderType.OIDC:
        return VerifiedEmailOpenID(
            config["client_id"],
            config["client_secret"],
            config["openid_config_url"],
            name=provider.name,
            base_scopes=list(BASE_SCOPES) + ["offline_access"],
        )
    if provider.provider_type is SSOProviderType.GOOGLE_OAUTH:
        return GoogleOAuth2(
            config["client_id"],
            config["client_secret"],
            scopes=list(GOOGLE_LOGIN_BASE_SCOPES),
            name=provider.name,
        )

    raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown OIDC provider")


def _get_cache_key(
    provider: SSOProvider, config: dict[str, Any]
) -> tuple[str, SSOProviderType, str]:
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return provider.name, provider.provider_type, config_hash


async def _get_oauth_client(
    provider: SSOProvider, config: dict[str, Any]
) -> BaseOAuth2[Any]:
    # Building an OIDC client fetches the discovery doc over the network, so
    # cache per provider+config. The TTL bounds staleness after an admin edit.
    cache_key = _get_cache_key(provider, config)
    cached_client = _CLIENT_CACHE.get(cache_key)
    if cached_client is not None:
        client, stamp = cached_client
        if time.monotonic() - stamp <= _CLIENT_CACHE_TTL_SECONDS:
            return client

    client = await run_in_threadpool(_build_client, provider, config)
    _CLIENT_CACHE[cache_key] = (client, time.monotonic())
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
        secure=WEB_DOMAIN.startswith("https"),
        httponly=True,
        samesite="lax",
    )


def _delete_pkce_cookie(response: Response, state: str) -> None:
    response.delete_cookie(
        key=get_pkce_cookie_name(state),
        path="/",
        secure=WEB_DOMAIN.startswith("https"),
        httponly=True,
        samesite="lax",
    )


def _decode_and_validate_state(request: Request, state: str) -> dict[str, str]:
    try:
        state_data = decode_jwt(state, USER_AUTH_SECRET, [STATE_TOKEN_AUDIENCE])
    except jwt.DecodeError:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            getattr(
                ErrorCode,
                "ACCESS_TOKEN_DECODE_ERROR",
                "ACCESS_TOKEN_DECODE_ERROR",
            ),
        )
    except jwt.ExpiredSignatureError:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            getattr(
                ErrorCode,
                "ACCESS_TOKEN_ALREADY_EXPIRED",
                "ACCESS_TOKEN_ALREADY_EXPIRED",
            ),
        )
    except jwt.PyJWTError:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            getattr(
                ErrorCode,
                "ACCESS_TOKEN_DECODE_ERROR",
                "ACCESS_TOKEN_DECODE_ERROR",
            ),
        )

    cookie_csrf_token = request.cookies.get(CSRF_TOKEN_COOKIE_NAME)
    state_csrf_token = state_data.get(CSRF_TOKEN_KEY)
    if (
        not cookie_csrf_token
        or not state_csrf_token
        or not secrets.compare_digest(cookie_csrf_token, state_csrf_token)
    ):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            getattr(ErrorCode, "OAUTH_INVALID_STATE", "OAUTH_INVALID_STATE"),
        )

    return state_data


@router.get("/{provider_name}/authorize")
async def oidc_login_for_provider(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_session),
) -> Response:
    provider, config = _resolve_oidc_provider(db_session, provider_name)
    client = await _get_oauth_client(provider, config)
    redirect_uri = f"{WEB_DOMAIN}/auth/oidc/{provider_name}/callback"
    next_url = sanitize_next_url(request.query_params.get("next"))
    csrf_token = generate_csrf_token()
    state = generate_state_token(
        {"next_url": next_url, CSRF_TOKEN_KEY: csrf_token},
        USER_AUTH_SECRET,
    )

    extras: dict[str, str] | None = None
    if provider.provider_type is SSOProviderType.GOOGLE_OAUTH:
        extras = {"access_type": "offline", "prompt": "consent"}

    code_verifier: str | None = None
    if OIDC_PKCE_ENABLED:
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
    if OIDC_PKCE_ENABLED:
        if code_verifier is None:
            raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Missing PKCE verifier")
        _set_oauth_cookie(
            response,
            key=get_pkce_cookie_name(state),
            value=code_verifier,
        )

    return response


@router.get("/{provider_name}/callback")
async def oidc_login_callback_for_provider(
    provider_name: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db_session: Session = Depends(get_session),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    provider, config = _resolve_oidc_provider(db_session, provider_name)
    client = await _get_oauth_client(provider, config)
    redirect_uri = f"{WEB_DOMAIN}/auth/oidc/{provider_name}/callback"

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

    state_data = _decode_and_validate_state(request, state)

    code_verifier: str | None = None
    if OIDC_PKCE_ENABLED:
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
        allowed_email_domains_override=provider.allowed_email_domains,
    )

    if OIDC_PKCE_ENABLED:
        _delete_pkce_cookie(redirect_response, state)

    return redirect_response
