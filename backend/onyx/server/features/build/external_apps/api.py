import ipaddress
import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    ExternalAppType,
    Permission,
    SandboxStatus,
)
from onyx.db.external_app import (
    get_external_apps,
    get_user_credentials_by_app_id,
)
from onyx.db.external_app_readiness import (
    required_user_credential_keys,
)
from onyx.db.models import ExternalApp, ExternalAppUserCredential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import (
    get_provider_for_app,
)
from onyx.server.features.build import connect_app
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.external_apps.models import (
    ConnectAppDecisionRequest,
    ExternalAppUserResponse,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.utils.encryption import mask_string
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()


def _to_user_response(
    app: ExternalApp, user_cred: ExternalAppUserCredential | None
) -> ExternalAppUserResponse:
    """User-facing view of an app. ``credential_keys`` = auth_template keys the
    org hasn't pre-filled; ``credential_values`` = the user's masked stored
    values for those keys (stale keys filtered out).
    """
    required_keys = required_user_credential_keys(
        app.auth_template, app.organization_credentials.get_value(apply_mask=False)
    )
    stored_raw = (
        user_cred.user_credentials.get_value(apply_mask=False)
        if user_cred is not None
        else {}
    )
    credential_values = {
        key: mask_string(str(stored_raw[key]))
        for key in required_keys
        if key in stored_raw
    }
    authenticated = all(key in stored_raw for key in required_keys)
    service_urls: list[str] = []
    for pattern in app.upstream_url_patterns:
        if app.app_type != ExternalAppType.CUSTOM:
            pattern = pattern.removeprefix("^")
        authority = pattern.partition("://")[2].split("/", 1)[0].rsplit("@", 1)[-1]
        if app.app_type != ExternalAppType.CUSTOM:
            if "?" in authority or re.search(r"(?<!\\)\.", authority):
                continue
            pattern = pattern.replace(r"\.", ".").replace(r"\-", "-")
        host_port, separator, query = authority.partition("?")
        if separator and "=" not in query:
            continue
        if re.search(r"[\s*+|(){}^$]", host_port):
            continue
        try:
            parsed = urlsplit(pattern)
            hostname = parsed.hostname
            port = parsed.port
            if parsed.scheme not in ("http", "https") or not hostname:
                continue
            if ":" in hostname:
                hostname = f"[{ipaddress.IPv6Address(hostname).compressed}]"
            elif not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*",
                hostname,
            ):
                continue
        except ValueError:
            continue
        origin = f"{parsed.scheme}://{hostname}"
        if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
            origin += f":{port}"
        if origin not in service_urls:
            service_urls.append(origin)

    return ExternalAppUserResponse(
        id=app.id,
        name=app.name,
        app_type=app.app_type,
        credential_keys=required_keys,
        credential_values=credential_values,
        authenticated=authenticated,
        supports_oauth=isinstance(get_provider_for_app(app), OAuthExternalAppProvider),
        service_urls=service_urls,
    )


# =============================================================================
# Admin Endpoints
# =============================================================================


# =============================================================================
# User Endpoints
# =============================================================================


@router.get("/apps")
def list_external_apps(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppUserResponse]:
    """List enabled external apps with the calling user's credential state: the
    keys the user must supply, the values already stored, and an
    ``authenticated`` flag. Org credentials and the raw auth template aren't
    exposed.
    """
    apps = get_external_apps(db_session=db_session, enabled_only=True)
    user_creds_by_app = get_user_credentials_by_app_id(
        db_session=db_session, user_id=user.id
    )
    return [_to_user_response(app, user_creds_by_app.get(app.id)) for app in apps]


@router.post("/apps/connect/{request_id}/decision")
def resolve_connect_app_request(
    request_id: str,
    body: ConnectAppDecisionRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Answer a pending ``connect_app`` request: load the stashed context and
    answer opencode on the user's sandbox — connected (allow) / declined
    (reject). Idempotent; an expired or already-answered request is a no-op.
    """
    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    pending = connect_app.load_pending(request_id, cache)
    if pending is None:
        return

    # Scope to the caller's own session before touching their sandbox.
    if get_build_session(UUID(pending.build_session_id), user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Connect request not found.")
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    if sandbox is None or sandbox.status != SandboxStatus.RUNNING:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE, "Sandbox is not running.")

    answered = get_sandbox_manager().answer_connect_app_permission(
        sandbox.id,
        opencode_session_id=pending.opencode_session_id,
        perm_id=pending.perm_id,
        directory=pending.directory,
        allow=body.decision == connect_app.ConnectAppDecision.CONNECTED,
    )
    if not answered:
        # Leave the pending record intact (TTL) so the user can retry
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Could not reach the sandbox to apply your choice — please try again.",
        )
    connect_app.clear_pending(request_id, cache)
