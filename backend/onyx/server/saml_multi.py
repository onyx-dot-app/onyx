import base64
import uuid
from typing import Any
from typing import NoReturn

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from fastapi_users.authentication import Strategy
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML
from sqlalchemy.orm import Session

from onyx.auth.users import auth_backend
from onyx.auth.users import fastapi_users
from onyx.auth.users import get_user_manager
from onyx.auth.users import UserManager
from onyx.configs.app_configs import REQUIRE_EMAIL_VERIFICATION
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.models import User
from onyx.db.sso_provider import fetch_sso_provider_by_name
from onyx.db.sso_provider import fetch_sso_providers
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.saml import _sanitize_relay_state
from onyx.server.saml import EMAIL_ATTRIBUTE_KEYS
from onyx.server.saml import EMAIL_ATTRIBUTE_KEYS_LOWER
from onyx.server.saml import prepare_from_fastapi_request
from onyx.server.saml import SAMLAuthorizeResponse
from onyx.server.saml import upsert_saml_user
from onyx.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(prefix="/auth/saml")


def build_saml_settings(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": config["sp_entity_id"],
            "assertionConsumerService": {
                "url": f"{WEB_DOMAIN}/auth/saml/callback",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "x509cert": config.get("sp_x509_cert") or "",
            "privateKey": config.get("sp_private_key") or "",
        },
        "idp": {
            "entityId": config["idp_entity_id"],
            "singleSignOnService": {
                "url": config["idp_sso_url"],
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": config["idp_x509_cert"],
        },
    }


def _has_required_saml_settings(config: dict[str, Any]) -> bool:
    required_fields = (
        "idp_entity_id",
        "idp_sso_url",
        "idp_x509_cert",
        "sp_entity_id",
    )
    return all(
        isinstance(config.get(field), str) and config.get(field)
        for field in required_fields
    )


def _resolve_saml_provider(
    db_session: Session, provider_name: str
) -> tuple[SSOProvider, dict[str, Any]]:
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

    config = provider.config.get_value(apply_mask=False)
    if not _has_required_saml_settings(config):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown SAML provider")

    return provider, config


def _resolve_saml_provider_by_issuer(
    db_session: Session, issuer: str
) -> tuple[SSOProvider, dict[str, Any]]:
    for provider in fetch_sso_providers(db_session=db_session, enabled_only=True):
        if (
            provider.provider_type is not SSOProviderType.SAML
            or provider.config is None
        ):
            continue

        config = provider.config.get_value(apply_mask=False)
        if not _has_required_saml_settings(config):
            continue
        if config.get("idp_entity_id") == issuer:
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
    request: Request, settings: dict[str, Any]
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


def _extract_user_email(auth: OneLogin_Saml2_Auth, config: dict[str, Any]) -> str:
    configured_email_attribute = config.get("email_attribute")
    if isinstance(configured_email_attribute, str) and configured_email_attribute:
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
    if isinstance(configured_email_attribute, str) and configured_email_attribute:
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
async def saml_login_callback(
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
