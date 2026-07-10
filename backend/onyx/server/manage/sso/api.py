from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import SSOProvider
from onyx.db.models import User
from onyx.db.sso_provider import create_sso_provider
from onyx.db.sso_provider import fetch_sso_providers
from onyx.db.sso_provider import set_sso_provider_enabled
from onyx.db.sso_provider import update_sso_provider
from onyx.db.sso_provider import validate_sso_config
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.sso.models import SSOProviderCreateRequest
from onyx.server.manage.sso.models import SSOProviderEnabledRequest
from onyx.server.manage.sso.models import SSOProviderResponse
from onyx.server.manage.sso.models import SSOProviderUpdateRequest
from onyx.utils.encryption import mask_credential_dict
from onyx.utils.encryption import reject_masked_credentials

admin_router = APIRouter(prefix="/admin/sso")


def _restore_masked_value(incoming: Any, stored: Any, masked_stored: Any) -> Any:
    if (
        isinstance(incoming, dict)
        and isinstance(stored, dict)
        and isinstance(masked_stored, dict)
    ):
        restored = dict(incoming)
        for key, value in incoming.items():
            if key not in stored or key not in masked_stored:
                continue
            restored[key] = _restore_masked_value(
                value, stored[key], masked_stored[key]
            )
        return restored

    if (
        isinstance(incoming, list)
        and isinstance(stored, list)
        and isinstance(masked_stored, list)
    ):
        restored_list = list(incoming)
        for index, value in enumerate(incoming):
            if index >= len(stored) or index >= len(masked_stored):
                continue
            restored_list[index] = _restore_masked_value(
                value,
                stored[index],
                masked_stored[index],
            )
        return restored_list

    if incoming == masked_stored:
        return stored

    return incoming


def _restore_masked_config(
    incoming: dict[str, Any], stored: dict[str, Any]
) -> dict[str, Any]:
    restored = _restore_masked_value(
        incoming,
        stored,
        mask_credential_dict(stored),
    )
    if not isinstance(restored, dict):
        return incoming
    return restored


def _fetch_sso_provider_or_raise(db_session: Session, provider_id: int) -> SSOProvider:
    provider = db_session.get(SSOProvider, provider_id)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"SSO provider {provider_id} does not exist",
        )
    return provider


@admin_router.get("/provider")
def list_sso_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[SSOProviderResponse]:
    return [
        SSOProviderResponse.from_model(provider, WEB_DOMAIN)
        for provider in fetch_sso_providers(db_session, enabled_only=False)
    ]


@admin_router.post("/provider")
def create_sso_provider_endpoint(
    request: SSOProviderCreateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SSOProviderResponse:
    try:
        reject_masked_credentials(request.config)
        provider = create_sso_provider(
            db_session=db_session,
            name=request.name,
            display_name=request.display_name,
            provider_type=request.provider_type,
            config=request.config,
            allowed_email_domains=request.allowed_email_domains,
        )
    except IntegrityError as e:
        db_session.rollback()
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"SSO provider with name {request.name} already exists",
        ) from e
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    return SSOProviderResponse.from_model(provider, WEB_DOMAIN)


@admin_router.patch("/provider/{provider_id}")
def update_sso_provider_endpoint(
    provider_id: int,
    request: SSOProviderUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SSOProviderResponse:
    provider = _fetch_sso_provider_or_raise(db_session, provider_id)

    merged_config: dict[str, Any] | None = None
    if request.config is not None:
        stored_config = (
            provider.config.get_value(apply_mask=False) if provider.config else {}
        )
        merged_config = _restore_masked_config(request.config, stored_config)
        reject_masked_credentials(merged_config)
        validate_sso_config(provider.provider_type, merged_config)

    try:
        updated_provider = update_sso_provider(
            db_session=db_session,
            provider_id=provider_id,
            display_name=request.display_name,
            config=merged_config,
            allowed_email_domains=request.allowed_email_domains,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    return SSOProviderResponse.from_model(updated_provider, WEB_DOMAIN)


@admin_router.post("/provider/{provider_id}/enabled")
def set_sso_provider_enabled_endpoint(
    provider_id: int,
    request: SSOProviderEnabledRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SSOProviderResponse:
    _fetch_sso_provider_or_raise(db_session, provider_id)

    try:
        provider = set_sso_provider_enabled(
            db_session=db_session,
            provider_id=provider_id,
            enabled=request.enabled,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    return SSOProviderResponse.from_model(provider, WEB_DOMAIN)
