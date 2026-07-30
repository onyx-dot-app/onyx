from fastapi import APIRouter, Depends, HTTPException

from ee.onyx.db.user_tenant_mapping import (
    accept_user_invite,
    approve_user_invite,
    deny_user_invite,
)
from ee.onyx.server.tenants.models import (
    ApproveUserRequest,
    PendingUserSnapshot,
    RequestInviteRequest,
)
from onyx.auth.invited_users import (
    get_pending_users,
    write_pending_users,
)
from onyx.auth.permissions import require_permission
from onyx.auth.users import User
from onyx.db.enums import Permission
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

router = APIRouter(prefix="/tenants")


def invite_self_to_tenant(email: str, tenant_id: str) -> None:
    # The pending list lives in the target tenant's KV store, not the caller's.
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        pending_users = get_pending_users()
        if email in pending_users:
            return
        write_pending_users(pending_users + [email])
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@router.post("/users/invite/request")
async def request_invite(
    invite_request: RequestInviteRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    try:
        invite_self_to_tenant(user.email, invite_request.tenant_id)
    except Exception as e:
        logger.exception(
            "Failed to invite self to tenant %s: %s", invite_request.tenant_id, e
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/pending")
def list_pending_users(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> list[PendingUserSnapshot]:
    pending_emails = get_pending_users()
    return [PendingUserSnapshot(email=email) for email in pending_emails]


@router.post("/users/invite/approve")
async def approve_user(
    approve_user_request: ApproveUserRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    tenant_id = get_current_tenant_id()
    approve_user_invite(approve_user_request.email, tenant_id)


@router.post("/users/invite/accept")
async def accept_invite(
    invite_request: RequestInviteRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> None:
    """
    Accept an invitation to join a tenant.
    """
    try:
        accept_user_invite(
            user.email,
            invite_request.tenant_id,
            [
                (account.oauth_name, account.account_id)
                for account in user.oauth_accounts
            ],
        )
    except Exception as e:
        logger.exception("Failed to accept invite: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to accept invitation")


@router.post("/users/invite/deny")
async def deny_invite(
    invite_request: RequestInviteRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> None:
    """
    Deny an invitation to join a tenant.
    """
    try:
        deny_user_invite(user.email, invite_request.tenant_id)
    except Exception as e:
        logger.exception("Failed to deny invite: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to deny invitation")
