from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import TracingProviderConfig
from onyx.db.models import User
from onyx.db.tracing import delete_tracing_provider
from onyx.db.tracing import fetch_tracing_provider
from onyx.db.tracing import upsert_tracing_provider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.tracing.models import TracingProviderTestRequest
from onyx.server.manage.tracing.models import TracingProviderUpsertRequest
from onyx.server.manage.tracing.models import TracingProviderView
from onyx.tracing.provider_config import BraintrustConfig
from onyx.tracing.provider_config import EffectiveTracingConfig
from onyx.tracing.provider_config import LangfuseConfig
from onyx.tracing.provider_config import resolve_effective_tracing_config
from onyx.tracing.validation import validate_tracing_credentials
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.enums import TracingProviderType

logger = setup_logger()


def _reject_if_multi_tenant() -> None:
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Tracing provider configuration is not available on this deployment.",
        )


admin_router = APIRouter(
    prefix="/admin/tracing", dependencies=[Depends(_reject_if_multi_tenant)]
)


def _env_config_for(
    provider_type: TracingProviderType, effective: EffectiveTracingConfig
) -> dict[str, str]:
    """Non-secret settings to surface for an env-sourced provider (for the UI/adopt)."""
    if provider_type == TracingProviderType.BRAINTRUST and effective.braintrust:
        return {"project": effective.braintrust.project}
    if provider_type == TracingProviderType.LANGFUSE and effective.langfuse:
        config = {"public_key": effective.langfuse.public_key}
        if effective.langfuse.host:
            config["host"] = effective.langfuse.host
        return config
    return {}


def _build_view(
    provider_type: TracingProviderType,
    row: TracingProviderConfig | None,
    effective: EffectiveTracingConfig,
) -> TracingProviderView:
    if provider_type == TracingProviderType.BRAINTRUST:
        is_connected = effective.braintrust is not None
    elif provider_type == TracingProviderType.LANGFUSE:
        is_connected = effective.langfuse is not None
    else:
        is_connected = False
    if row is not None:
        return TracingProviderView(
            provider_type=provider_type,
            connected=is_connected,
            source="db",
            enabled=row.enabled,
            config=row.config or {},
            masked_api_key=(
                row.api_key.get_value(apply_mask=True) if row.api_key else None
            ),
        )
    if is_connected:
        return TracingProviderView(
            provider_type=provider_type,
            connected=True,
            source="env",
            enabled=True,
            config=_env_config_for(provider_type, effective),
        )
    return TracingProviderView(
        provider_type=provider_type,
        connected=False,
        source="none",
        enabled=False,
    )


@admin_router.get("/providers")
def list_tracing_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TracingProviderView]:
    effective = resolve_effective_tracing_config()
    return [
        _build_view(
            provider_type, fetch_tracing_provider(provider_type, db_session), effective
        )
        for provider_type in TracingProviderType
    ]


@admin_router.post("/providers")
def upsert_tracing_provider_endpoint(
    request: TracingProviderUpsertRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> TracingProviderView:
    upsert_tracing_provider(
        provider_type=request.provider_type,
        api_key=request.api_key,
        api_key_changed=request.api_key_changed,
        config=request.config,
        enabled=request.enabled,
        updated_by_user_id=user.id if user else None,
        db_session=db_session,
    )
    db_session.commit()

    effective = resolve_effective_tracing_config()
    row = fetch_tracing_provider(request.provider_type, db_session)
    return _build_view(request.provider_type, row, effective)


@admin_router.delete("/providers/{provider_type}")
def disconnect_tracing_provider(
    provider_type: TracingProviderType,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> TracingProviderView:
    delete_tracing_provider(provider_type, db_session)
    db_session.commit()

    effective = resolve_effective_tracing_config()
    return _build_view(provider_type, None, effective)


@admin_router.post("/providers/test")
def test_tracing_provider(
    request: TracingProviderTestRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    config = request.config or {}
    api_key = request.api_key
    if request.use_stored_key:
        row = fetch_tracing_provider(request.provider_type, db_session)
        if row is None or not row.api_key:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                "No stored key found for this provider.",
            )
        api_key = row.api_key.get_value(apply_mask=False)
        config = {**(row.config or {}), **config}

    try:
        validate_tracing_credentials(
            provider_type=request.provider_type, api_key=api_key, config=config
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    return {"status": "ok"}


@admin_router.post("/providers/{provider_type}/adopt-env")
def adopt_env_tracing_provider(
    provider_type: TracingProviderType,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> TracingProviderView:
    """Copy an env-var-configured provider into a DB row so it can be managed in the UI."""
    if fetch_tracing_provider(provider_type, db_session) is not None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Provider is already configured in the UI.",
        )

    effective = resolve_effective_tracing_config()
    api_key, config = _env_credentials(provider_type, effective)
    if api_key is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "No environment-configured credentials found for this provider.",
        )

    upsert_tracing_provider(
        provider_type=provider_type,
        api_key=api_key,
        api_key_changed=True,
        config=config,
        enabled=True,
        updated_by_user_id=user.id if user else None,
        db_session=db_session,
    )
    db_session.commit()

    effective = resolve_effective_tracing_config()
    row = fetch_tracing_provider(provider_type, db_session)
    return _build_view(provider_type, row, effective)


def _env_credentials(
    provider_type: TracingProviderType, effective: EffectiveTracingConfig
) -> tuple[str | None, dict[str, str]]:
    if provider_type == TracingProviderType.BRAINTRUST and isinstance(
        effective.braintrust, BraintrustConfig
    ):
        return effective.braintrust.api_key, {"project": effective.braintrust.project}
    if provider_type == TracingProviderType.LANGFUSE and isinstance(
        effective.langfuse, LangfuseConfig
    ):
        config = {"public_key": effective.langfuse.public_key}
        if effective.langfuse.host:
            config["host"] = effective.langfuse.host
        return effective.langfuse.secret_key, config
    return None, {}
