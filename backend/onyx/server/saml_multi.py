import base64
import uuid
from typing import Any, NoReturn, TypedDict

from fastapi import APIRouter, Depends, Request, Response
from fastapi_users.authentication import Strategy
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth.sso_web_error import redirect_sso_errors_to_web
from onyx.auth.users import UserManager, auth_backend, fastapi_users, get_user_manager
from onyx.configs.app_configs import REQUIRE_EMAIL_VERIFICATION, WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider, User
from onyx.db.sso_provider import (
    SAMLProviderConfig,
    fetch_sso_provider_by_name,
    fetch_sso_providers,
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
router = APIRouter(prefix="/auth/saml")


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


def _extract_issuer_from_saml_response(encoded_response: str) -> str:
    """Read the unverified issuer to select which provider's cert to validate
    against. Safe because process_response still checks the signature against the
    resolved cert, so an attacker only picks which cert they fail against."""
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
        if nodes:
            issuer = OneLogin_Saml2_XML.element_text(nodes[0])
            if issuer:
                return issuer

    raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "SAML response missing issuer")


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
) -> SAMLAuthorizeResponse:
    _provider, config = _resolve_saml_provider(db_session, "saml")
    settings = build_saml_settings(config)
    auth = await _build_saml_auth(request, settings)
    return_to = _sanitize_relay_state(request.query_params.get("next"))
    callback_url = auth.login(return_to=return_to)
    return SAMLAuthorizeResponse(authorization_url=callback_url)


@router.get("/callback")
@redirect_sso_errors_to_web
async def saml_login_callback_get(
    request: Request,
    db_session: Session = Depends(get_session),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    return await _process_saml_callback(
        request,
        db_session,
        strategy,
        user_manager,
    )


@router.post("/callback")
@redirect_sso_errors_to_web
async def saml_login_callback_post(
    request: Request,
    db_session: Session = Depends(get_session),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    return await _process_saml_callback(
        request,
        db_session,
        strategy,
        user_manager,
    )


@router.get("/{provider_name}/authorize")
async def saml_login_for_provider(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_session),
) -> SAMLAuthorizeResponse:
    _provider, config = _resolve_saml_provider(db_session, provider_name)
    settings = build_saml_settings(config)
    auth = await _build_saml_auth(request, settings)
    return_to = _sanitize_relay_state(request.query_params.get("next"))
    callback_url = auth.login(return_to=return_to)
    return SAMLAuthorizeResponse(authorization_url=callback_url)


async def _process_saml_callback(
    request: Request,
    db_session: Session,
    strategy: Strategy[User, uuid.UUID],
    user_manager: UserManager,
) -> Response:
    req = await prepare_from_fastapi_request(request)
    encoded_response = req["post_data"].get("SAMLResponse") or req["get_data"].get(
        "SAMLResponse"
    )
    if not isinstance(encoded_response, str) or not encoded_response:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "missing SAML response")

    issuer = _extract_issuer_from_saml_response(encoded_response)
    provider, config = _resolve_saml_provider_by_issuer(db_session, issuer)
    settings = build_saml_settings(config)

    auth = OneLogin_Saml2_Auth(req, old_settings=settings)
    auth.process_response()

    errors = auth.get_errors()
    if errors:
        _raise_saml_access_denied(auth, "Access denied. Failed to parse SAML response.")

    if not auth.is_authenticated():
        _raise_saml_access_denied(auth, "Access denied. User was not authenticated.")

    user_email = _extract_user_email(auth, config)
    _enforce_allowed_email_domain(provider, user_email)

    user = await upsert_saml_user(email=user_email)
    # A deactivated account must not receive a session. The OIDC path gates this
    # in complete_login_flow. SAML gates it here since it logs the user in
    # directly.
    if not user.is_active:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Your account is deactivated. Contact your workspace admin.",
        )
    response = await auth_backend.login(strategy, user)
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
