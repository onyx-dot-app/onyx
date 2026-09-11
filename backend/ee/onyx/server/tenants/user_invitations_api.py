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
from ee.onyx.server.tenants.provisioning import get_tenant_by_domain_from_control_plane
from ee.onyx.server.tenants.tenant_management_api import (
    FORBIDDEN_COMMON_EMAIL_SUBSTRINGS,
)
from onyx.auth.invited_users import (
    get_pending_users,
    write_pending_users,
)
from onyx.auth.permissions import require_permission
from onyx.auth.users import User
from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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


def _assert_tenant_is_joinable(email: str, tenant_id: str) -> None:
    """Re-derive the same-domain gate the join flow shows in the UI. Without it the
    body's tenant_id is an unchecked write into any tenant's pending list."""
    domain = email.split("@")[-1]
    tenant = None
    if not any(substring in domain for substring in FORBIDDEN_COMMON_EMAIL_SUBSTRINGS):
        tenant = get_tenant_by_domain_from_control_plane(
            domain, get_current_tenant_id()
        )
    if tenant is None or tenant.tenant_id != tenant_id:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "No team found for this email domain")


@router.post("/users/invite/request")
async def request_invite(
    invite_request: RequestInviteRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    _assert_tenant_is_joinable(user.email, invite_request.tenant_id)
    try:
        invite_self_to_tenant(user.email, invite_request.tenant_id)
    except Exception as e:
        logger.exception(
            "Failed to invite self to tenant %s: %s", invite_request.tenant_id, e
        )
        raise HTTPException(status_code=500, detail="Failed to request invitation")


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
    # Approving rewrites the catalog row for this email in every tenant, so only
    # act on an address that asked to join this one.
    email = approve_user_request.email.lower()
    if email not in {pending.lower() for pending in get_pending_users()}:
        raise OnyxError(
            OnyxErrorCode.BAD_REQUEST, "No pending join request for this email"
        )

    tenant_id = get_current_tenant_id()
    approve_user_invite(email, tenant_id)


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
