import uuid
from typing import Any
from typing import NoReturn

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from fastapi_users.authentication import Strategy
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from sqlalchemy.orm import Session

from onyx.auth.users import auth_backend
from onyx.auth.users import get_user_manager
from onyx.auth.users import UserManager
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.models import User
from onyx.db.sso_provider import fetch_sso_provider_by_name
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


def build_saml_settings(config: dict[str, Any], provider_name: str) -> dict[str, Any]:
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": config["sp_entity_id"],
            "assertionConsumerService": {
                "url": f"{WEB_DOMAIN}/auth/saml/{provider_name}/callback",
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


def _resolve_saml_provider(
    db_session: Session, provider_name: str
) -> tuple[SSOProvider, dict[str, Any]]:
    # Resolve fail closed so disabled or misconfigured rows never become an oracle.
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
    return provider, provider.config.get_value(apply_mask=False)


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
    # Stops one company's email entering through another provider's button.
    if not provider.allowed_email_domains:
        return

    _, _, email_domain = email.rpartition("@")
    if email_domain.strip().lower() in provider.allowed_email_domains:
        return

    raise OnyxError(
        OnyxErrorCode.UNAUTHORIZED,
        "email domain not permitted for this provider",
    )


@router.get("/{provider_name}/authorize")
async def saml_login(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_session),
) -> SAMLAuthorizeResponse:
    _provider, config = _resolve_saml_provider(db_session, provider_name)
    settings = build_saml_settings(config, provider_name)
    auth = await _build_saml_auth(request, settings)
    return_to = _sanitize_relay_state(request.query_params.get("next"))
    callback_url = auth.login(return_to=return_to)
    return SAMLAuthorizeResponse(authorization_url=callback_url)


@router.get("/{provider_name}/callback")
async def saml_login_callback_get(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_session),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    return await _process_saml_callback(
        provider_name,
        request,
        db_session,
        strategy,
        user_manager,
    )


@router.post("/{provider_name}/callback")
async def saml_login_callback(
    provider_name: str,
    request: Request,
    db_session: Session = Depends(get_session),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    return await _process_saml_callback(
        provider_name,
        request,
        db_session,
        strategy,
        user_manager,
    )


async def _process_saml_callback(
    provider_name: str,
    request: Request,
    db_session: Session,
    strategy: Strategy[User, uuid.UUID],
    user_manager: UserManager,
) -> Response:
    provider, config = _resolve_saml_provider(db_session, provider_name)
    settings = build_saml_settings(config, provider_name)
    auth = await _build_saml_auth(request, settings)
    auth.process_response()

    errors = auth.get_errors()
    if len(errors) != 0:
        _raise_saml_access_denied(auth, "Access denied. Failed to parse SAML response.")

    if not auth.is_authenticated():
        _raise_saml_access_denied(auth, "Access denied. User was not authenticated.")

    user_email = _extract_user_email(auth, config)
    _enforce_allowed_email_domain(provider, user_email)

    user = await upsert_saml_user(email=user_email)
    response = await auth_backend.login(strategy, user)
    await user_manager.on_after_login(user, request, response)
    return response
