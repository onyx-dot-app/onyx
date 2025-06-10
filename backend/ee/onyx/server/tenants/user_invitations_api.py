from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from ee.onyx.server.tenants.models import ApproveUserRequest
from ee.onyx.server.tenants.models import PendingUserSnapshot
from ee.onyx.server.tenants.models import RequestInviteRequest
from ee.onyx.server.tenants.user_mapping import accept_user_invite
from ee.onyx.server.tenants.user_mapping import approve_user_invite
from ee.onyx.server.tenants.user_mapping import deny_user_invite
from ee.onyx.server.tenants.user_mapping import invite_self_to_tenant
from onyx.auth.invited_users import get_pending_users
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.auth.users import User
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/tenants")


@router.post("/users/invite/request")
async def request_invite(
    invite_request: RequestInviteRequest,
    user: User | None = Depends(current_admin_user),
) -> None:
    if user is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    try:
        invite_self_to_tenant(user.email, invite_request.tenant_id)
    except Exception as e:
        logger.exception(
            f"Failed to invite self to tenant {invite_request.tenant_id}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/pending")
def list_pending_users(
    _: User | None = Depends(current_admin_user),
) -> list[PendingUserSnapshot]:
    pending_emails = get_pending_users()
    return [PendingUserSnapshot(email=email) for email in pending_emails]


@router.post("/users/invite/approve")
async def approve_user(
    approve_user_request: ApproveUserRequest,
    _: User | None = Depends(current_admin_user),
) -> None:
    tenant_id = get_current_tenant_id()
    approve_user_invite(approve_user_request.email, tenant_id)


@router.post("/users/invite/accept")
async def accept_invite(
    invite_request: RequestInviteRequest,
    user: User | None = Depends(current_user),
) -> None:
    """
    Accept an invitation to join a tenant.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        accept_user_invite(user.email, invite_request.tenant_id)
    except Exception as e:
        logger.exception(f"Failed to accept invite: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to accept invitation")


@router.post("/users/invite/deny")
async def deny_invite(
    invite_request: RequestInviteRequest,
    user: User | None = Depends(current_user),
) -> None:
    """
    Deny an invitation to join a tenant.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        deny_user_invite(user.email, invite_request.tenant_id)
    except Exception as e:
        logger.exception(f"Failed to deny invite: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to deny invitation")
