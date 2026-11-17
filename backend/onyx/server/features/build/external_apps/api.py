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
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    Permission,
    SandboxStatus,
)
from onyx.db.integration import get_external_app_for_integration
from onyx.db.integration_connection import get_connection
from onyx.db.models import ExternalApp, Integration, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import (
    get_provider_for_app,
)
from onyx.integrations.connection_models import (
    ConnectionState,
    read_connection_secret,
)
from onyx.integrations.connections import credential_field_keys, integration_status
from onyx.integrations.craft import list_runnable_integrations
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
    app: ExternalApp, integration: Integration, user: User, db_session: Session
) -> ExternalAppUserResponse:
    """User-facing view of an app. ``credential_keys`` = the fields the user
    fills for an API key sign-in for each user; ``credential_values`` = the
    user's masked saved values for those keys.
    """
    required_keys = (
        credential_field_keys(integration)
        if integration.auth_method is IntegrationAuthMethod.API_KEY
        and integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
        else []
    )
    connection = (
        get_connection(db_session, integration.id, user.id) if required_keys else None
    )
    stored = read_connection_secret(connection).fields if connection else {}
    credential_values = {
        key: mask_string(stored[key]) for key in required_keys if key in stored
    }
    authenticated = (
        integration_status(integration, user, db_session).state
        is ConnectionState.CONNECTED
    )
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
        integration_id=integration.id,
        name=integration.name,
        app_type=app.app_type,
        credential_keys=required_keys,
        credential_values=credential_values,
        authenticated=authenticated,
        supports_oauth=isinstance(get_provider_for_app(app), OAuthExternalAppProvider),
        service_urls=service_urls,
    )


@router.get("/apps")
def list_external_apps(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppUserResponse]:
    """The external apps of the integrations the user runs, with the user's
    connection state: the keys the user must supply, the values already
    saved, and an ``authenticated`` flag."""
    responses: list[ExternalAppUserResponse] = []
    for integration in list_runnable_integrations(db_session, user.id):
        if integration.kind is not IntegrationKind.API:
            continue
        app = get_external_app_for_integration(integration.id, db_session)
        if app is not None:
            responses.append(_to_user_response(app, integration, user, db_session))
    return responses


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
