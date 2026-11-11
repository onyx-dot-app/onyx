import base64
import hashlib
import secrets
import time
import uuid
from typing import Any, NoReturn, TypedDict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi_users.authentication import Strategy
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.login_claims_capture import capture_saml_login_claims
from onyx.auth.sso_web_error import redirect_sso_errors_to_web
from onyx.auth.users import UserManager, auth_backend, fastapi_users, get_user_manager
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import REQUIRE_EMAIL_VERIFICATION, WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider, User
from onyx.db.sso_provider import (
    SAMLProviderConfig,
    fetch_sso_provider_by_name,
    fetch_sso_providers,
    sso_provider_type_supported,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.saml import (
    EMAIL_ATTRIBUTE_KEYS,
    EMAIL_ATTRIBUTE_KEYS_LOWER,
    SAMLAuthorizeResponse,
    _sanitize_relay_state,
    prepare_from_fastapi_request,
    upsert_saml_user,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_AUTHN_REQUEST_KEY_PREFIX = "saml:authn_request:v1"
_ASSERTION_KEY_PREFIX = "saml:assertion:v1"
_LOGIN_TICKET_KEY_PREFIX = "saml:login_ticket:v1"
_LOGIN_COOKIE_PREFIX = "samllogin"
_LOGIN_COOKIE_PATH = "/auth/saml"
_COOKIE_SECURE = WEB_DOMAIN.startswith("https")
# Bounds how long an unanswered AuthnRequest stays consumable. A login round
# trip through the IdP finishes well inside this.
_AUTHN_REQUEST_TTL_SECONDS = 10 * 60
# Replay window for an assertion whose SubjectConfirmationData carries no
# NotOnOrAfter, so the one-time-use record cannot expire before the assertion.
_ASSERTION_FALLBACK_TTL_SECONDS = 10 * 60
# Covers the one redirect between the validated callback and /complete.
_LOGIN_TICKET_TTL_SECONDS = 60
_NO_PENDING_REQUEST_MESSAGE = (
    "Access denied. SAML response does not answer a pending sign-in request."
)


def _reject_if_unsupported() -> None:
    """SAML resolves a login by scanning provider rows for the assertion's
    issuer, which cannot name a workspace on a deployment that has more than
    one, so the whole router is closed there rather than failing deeper in."""
    if not sso_provider_type_supported(SSOProviderType.SAML):
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "SAML sign-in is not available on this deployment.",
        )


router = APIRouter(prefix="/auth/saml", dependencies=[Depends(_reject_if_unsupported)])


# The OneLogin settings schema (its own key names, camelCase). We build and hand
# this to OneLogin_Saml2_Auth as old_settings.
class _SamlEndpoint(TypedDict):
    url: str
    binding: str


class _SamlSpSettings(TypedDict):
    entityId: str
    assertionConsumerService: _SamlEndpoint
    x509cert: str
    privateKey: str


class _SamlIdpSettings(TypedDict):
    entityId: str
    singleSignOnService: _SamlEndpoint
    x509cert: str


class _SamlSettings(TypedDict):
    strict: bool
    debug: bool
    sp: _SamlSpSettings
    idp: _SamlIdpSettings


def build_saml_settings(config: SAMLProviderConfig) -> _SamlSettings:
    """OneLogin old_settings built from a typed provider config. The ACS is fixed
    so every provider shares the one issuer-resolved callback."""
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": config.sp_entity_id,
            "assertionConsumerService": {
                "url": f"{WEB_DOMAIN}/auth/saml/callback",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "x509cert": config.sp_x509_cert or "",
            "privateKey": config.sp_private_key or "",
        },
        "idp": {
            "entityId": config.idp_entity_id,
            "singleSignOnService": {
                "url": config.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": config.idp_x509_cert,
        },
    }


def _parse_saml_config(raw: dict[str, Any]) -> SAMLProviderConfig | None:
    """Parse a stored config into the typed SAML model, or None when it is
    incomplete or malformed, so resolution fails closed instead of raising
    deeper in."""
    try:
        return SAMLProviderConfig.model_validate(raw)
    except ValidationError:
        return None


def _resolve_saml_provider(
    db_session: Session, provider_name: str
) -> tuple[SSOProvider, SAMLProviderConfig]:
    provider = fetch_sso_provider_by_name(
        db_session=db_session,
        name=provider_name,
        enabled_only=True,
    )
    if provider is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown SAML provider")
    if provider.provider_type is not SSOProviderType.SAML:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown SAML provider")
    if provider.config is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown SAML provider")

    config = _parse_saml_config(provider.config.get_value(apply_mask=False))
    if config is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown SAML provider")

    return provider, config


def _resolve_saml_provider_by_issuer(
    db_session: Session, issuer: str
) -> tuple[SSOProvider, SAMLProviderConfig]:
    for provider in fetch_sso_providers(db_session=db_session, enabled_only=True):
        if (
            provider.provider_type is not SSOProviderType.SAML
            or provider.config is None
        ):
            continue

        config = _parse_saml_config(provider.config.get_value(apply_mask=False))
        if config is None:
            continue
        if config.idp_entity_id == issuer:
            return provider, config

    raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "unrecognized SAML issuer")


class _SamlResponseHeader(BaseModel):
    issuer: str
    in_response_to: str | None


def _read_saml_response_header(encoded_response: str) -> _SamlResponseHeader:
    """Read the unverified issuer and InResponseTo. The issuer selects which
    provider's cert to validate against, which is safe because process_response
    still checks the signature, so an attacker only picks the cert they fail
    against. InResponseTo names the AuthnRequest the callback must find."""
    try:
        decoded = base64.b64decode(encoded_response)
        dom = OneLogin_Saml2_XML.to_etree(decoded)
    except Exception:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "malformed SAML response")

    for xpath in (
        "/samlp:Response/saml:Issuer",
        "/samlp:Response/saml:Assertion/saml:Issuer",
    ):
        nodes = OneLogin_Saml2_XML.query(dom, xpath)
        if not nodes:
            continue
        issuer = OneLogin_Saml2_XML.element_text(nodes[0])
        if issuer:
            return _SamlResponseHeader(
                issuer=issuer, in_response_to=dom.get("InResponseTo") or None
            )

    raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "SAML response missing issuer")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _cache_key(prefix: str, identifier: str) -> str:
    # Hashed because the identifier is IdP or attacker supplied.
    return f"{prefix}:{_sha256(identifier)}"


def _login_cookie_name(request_id: str) -> str:
    return f"{_LOGIN_COOKIE_PREFIX}_{_sha256(request_id)}"


class _PendingSamlRequest(BaseModel):
    idp_entity_id: str
    browser_secret_hash: str


class _SamlLoginTicket(BaseModel):
    """A validated SAML response, parked between the IdP's cross-site POST and
    the same-site GET that carries the login cookie."""

    request_id: str
    email: str
    provider_name: str
    browser_secret_hash: str
    attributes: dict[str, list[str]]
    next_path: str | None


def _remember_authn_request(request_id: str, idp_entity_id: str) -> str:
    """Record the AuthnRequest and return the secret that ties it to the browser
    that started sign-in, so a response captured from one browser cannot log
    another browser in (login CSRF)."""
    browser_secret = secrets.token_urlsafe(32)
    pending = _PendingSamlRequest(
        idp_entity_id=idp_entity_id, browser_secret_hash=_sha256(browser_secret)
    )
    get_cache_backend().set(
        _cache_key(_AUTHN_REQUEST_KEY_PREFIX, request_id),
        pending.model_dump_json(),
        ex=_AUTHN_REQUEST_TTL_SECONDS,
    )
    return browser_secret


def _consume_authn_request(in_response_to: str, issuer: str) -> _PendingSamlRequest:
    """One-time use: the id is removed as it is read, so a second response
    carrying the same InResponseTo, replayed or forged, finds nothing."""
    stored = get_cache_backend().getdel(
        _cache_key(_AUTHN_REQUEST_KEY_PREFIX, in_response_to)
    )
    if stored is None:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, _NO_PENDING_REQUEST_MESSAGE)
    pending = _PendingSamlRequest.model_validate_json(stored)
    if pending.idp_entity_id != issuer:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, _NO_PENDING_REQUEST_MESSAGE)
    return pending


def _require_login_cookie(request: Request, login: _SamlLoginTicket) -> str:
    """The cookie set on /authorize must come back on /complete, so a response
    captured in one browser cannot sign another browser in."""
    cookie_name = _login_cookie_name(login.request_id)
    browser_secret = request.cookies.get(cookie_name)
    if browser_secret is None or not secrets.compare_digest(
        login.browser_secret_hash, _sha256(browser_secret)
    ):
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Access denied. Sign-in must finish in the browser that started it.",
        )
    return cookie_name


def _reject_replayed_assertion(auth: OneLogin_Saml2_Auth) -> None:
    not_on_or_after = auth.get_last_assertion_not_on_or_after()
    ttl_seconds = (
        max(int(not_on_or_after - time.time()), 1)
        if not_on_or_after is not None
        else _ASSERTION_FALLBACK_TTL_SECONDS
    )
    stored = get_cache_backend().set_if_absent(
        _cache_key(_ASSERTION_KEY_PREFIX, auth.get_last_assertion_id()),
        b"1",
        ex=ttl_seconds,
    )
    if not stored:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED, "Access denied. SAML assertion already used."
        )


async def _build_saml_auth(
    request: Request, settings: _SamlSettings
) -> OneLogin_Saml2_Auth:
    req = await prepare_from_fastapi_request(request)
    return OneLogin_Saml2_Auth(req, old_settings=settings)


def _raise_saml_access_denied(auth: OneLogin_Saml2_Auth, detail: str) -> NoReturn:
    logger.error(
        "%s SAML errors: %s %s",
        detail,
        ", ".join(auth.get_errors()),
        auth.get_last_error_reason(),
    )
    raise OnyxError(OnyxErrorCode.UNAUTHORIZED, detail)


def _first_attribute_value(values: object) -> str | None:
    if not isinstance(values, list) or not values:
        return None

    first_value = values[0]
    if not isinstance(first_value, str) or not first_value:
        return None

    return first_value


def _extract_user_email(auth: OneLogin_Saml2_Auth, config: SAMLProviderConfig) -> str:
    configured_email_attribute = config.email_attribute
    if configured_email_attribute:
        configured_email = _first_attribute_value(
            auth.get_attribute(configured_email_attribute)
        )
        if configured_email:
            return configured_email

    for attribute_key in EMAIL_ATTRIBUTE_KEYS:
        attribute_email = _first_attribute_value(auth.get_attribute(attribute_key))
        if attribute_email:
            return attribute_email

    fallback_keys_lower = set(EMAIL_ATTRIBUTE_KEYS_LOWER)
    if configured_email_attribute:
        fallback_keys_lower.add(configured_email_attribute.lower())

    attributes = auth.get_attributes()
    for key, values in attributes.items():
        if isinstance(key, str) and key.lower() in fallback_keys_lower:
            attribute_email = _first_attribute_value(values)
            if attribute_email:
                return attribute_email

    logger.debug("Received SAML attributes without email: %s", list(attributes.keys()))
    _raise_saml_access_denied(
        auth, "Access denied. Email attribute missing from SAML response."
    )


def _enforce_allowed_email_domain(provider: SSOProvider, email: str) -> None:
    if not provider.allowed_email_domains:
        return

    _, _, email_domain = email.rpartition("@")
    if email_domain.strip().lower() in provider.allowed_email_domains:
        return

    raise OnyxError(
        OnyxErrorCode.UNAUTHORIZED,
        "email domain not permitted for this provider",
    )


@router.get("/authorize")
async def saml_login(
    request: Request,
    db_session: Session = Depends(get_session),
) -> Response:
    _provider, config = _resolve_saml_provider(db_session, "saml")
    return await _start_saml_login(request, config)


async def _start_saml_login(request: Request, config: SAMLProviderConfig) -> Response:
    settings = build_saml_settings(config)
    auth = await _build_saml_auth(request, settings)
    return_to = _sanitize_relay_state(request.query_params.get("next"))
    callback_url = auth.login(return_to=return_to)
    request_id = auth.get_last_request_id()
    browser_secret = _remember_authn_request(request_id, config.idp_entity_id)

    response = JSONResponse(
        content=SAMLAuthorizeResponse(authorization_url=callback_url).model_dump()
    )
    # Lax: the cookie is read on the same-site GET to /complete, never on the
    # IdP's cross-site POST, so it needs neither SameSite=None nor https.
    response.set_cookie(
        key=_login_cookie_name(request_id),
        value=browser_secret,
        max_age=_AUTHN_REQUEST_TTL_SECONDS,
        path=_LOGIN_COOKIE_PATH,
        secure=_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/callback")
@redirect_sso_errors_to_web
async def saml_login_callback_post(
    request: Request,
    db_session: Session = Depends(get_session),
) -> Response:
    return await _process_saml_callback(request, db_session)


@router.get("/complete")
@redirect_sso_errors_to_web
async def saml_login_complete(
    request: Request,
    ticket: str,
    db_session: Session = Depends(get_session),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    return await _complete_saml_login(
        request, ticket, db_session, strategy, user_manager
    )


@router.get("/{provider_name}/authorize")
async def saml_login_for_provider(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_session),
) -> Response:
    _provider, config = _resolve_saml_provider(db_session, provider_name)
    return await _start_saml_login(request, config)


async def _process_saml_callback(request: Request, db_session: Session) -> Response:
    """Validate the IdP's POST and park the result behind a one-time ticket.
    The browser follows a redirect to /complete, a same-site GET on which its
    login cookie arrives, which the cross-site POST cannot carry."""
    req = await prepare_from_fastapi_request(request)
    encoded_response = req["post_data"].get("SAMLResponse")
    if not isinstance(encoded_response, str) or not encoded_response:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "missing SAML response")

    header = _read_saml_response_header(encoded_response)
    # The library only compares InResponseTo when the response carries one, so
    # unsolicited and IdP-initiated responses are refused here.
    if header.in_response_to is None:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Access denied. SAML response does not answer a sign-in request.",
        )
    pending = _consume_authn_request(header.in_response_to, header.issuer)
    provider, config = _resolve_saml_provider_by_issuer(db_session, header.issuer)
    settings = build_saml_settings(config)

    auth = OneLogin_Saml2_Auth(req, old_settings=settings)
    auth.process_response(request_id=header.in_response_to)

    errors = auth.get_errors()
    if errors:
        _raise_saml_access_denied(auth, "Access denied. Failed to parse SAML response.")

    if not auth.is_authenticated():
        _raise_saml_access_denied(auth, "Access denied. User was not authenticated.")

    _reject_replayed_assertion(auth)
    user_email = _extract_user_email(auth, config)
    _enforce_allowed_email_domain(provider, user_email)

    relay_state = req["post_data"].get("RelayState")
    login = _SamlLoginTicket(
        request_id=header.in_response_to,
        email=user_email,
        provider_name=provider.name or "saml",
        browser_secret_hash=pending.browser_secret_hash,
        attributes=auth.get_attributes(),
        next_path=_sanitize_relay_state(
            relay_state if isinstance(relay_state, str) else None
        ),
    )
    ticket = secrets.token_urlsafe(32)
    get_cache_backend().set(
        _cache_key(_LOGIN_TICKET_KEY_PREFIX, ticket),
        login.model_dump_json(),
        ex=_LOGIN_TICKET_TTL_SECONDS,
    )
    return RedirectResponse(
        f"{WEB_DOMAIN}/auth/saml/complete?ticket={ticket}", status_code=303
    )


async def _complete_saml_login(
    request: Request,
    ticket: str,
    db_session: Session,
    strategy: Strategy[User, uuid.UUID],
    user_manager: UserManager,
) -> Response:
    stored = get_cache_backend().getdel(_cache_key(_LOGIN_TICKET_KEY_PREFIX, ticket))
    if stored is None:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED, "Access denied. Sign-in expired, try again."
        )
    login = _SamlLoginTicket.model_validate_json(stored)
    login_cookie_name = _require_login_cookie(request, login)
    # The provider may have been disabled or deleted since the callback ran.
    provider, _config = _resolve_saml_provider(db_session, login.provider_name)
    _enforce_allowed_email_domain(provider, login.email)

    user = await upsert_saml_user(email=login.email)
    # A deactivated account must not receive a session. The OIDC path gates this
    # in complete_login_flow. SAML gates it here since it logs the user in
    # directly.
    if not user.is_active:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Your account is deactivated. Contact your workspace admin.",
        )
    # Best-effort directory-profile capture from the SAML assertion attributes.
    await capture_saml_login_claims(login.email, login.attributes, login.provider_name)

    # auth_backend.login() answers a bare 204 meant for a JS caller. This is a
    # browser navigation, so carry its session cookie on a redirect instead.
    login_response = await auth_backend.login(strategy, user)
    response = RedirectResponse(
        f"{WEB_DOMAIN}{login.next_path or '/'}", status_code=302
    )
    for cookie in login_response.headers.getlist("set-cookie"):
        response.headers.append("set-cookie", cookie)
    response.delete_cookie(
        key=login_cookie_name,
        path=_LOGIN_COOKIE_PATH,
        secure=_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    await user_manager.on_after_login(user, request, response)
    return response


@router.post("/logout")
async def saml_logout(
    user_token: tuple[User, str] = Depends(
        fastapi_users.authenticator.current_user_token(
            active=True, verified=REQUIRE_EMAIL_VERIFICATION
        )
    ),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
) -> Response:
    user, token = user_token
    return await auth_backend.logout(strategy, user, token)
