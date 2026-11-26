from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.db.build_session import get_build_session
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    Permission,
    SandboxStatus,
)
from onyx.db.models import User
from onyx.db.sandbox import get_sandbox_by_user_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build import connect_app
from onyx.server.features.build.external_apps.models import (
    ConnectAppDecisionRequest,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()


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
