"""
Avatar permission request API endpoints.
"""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import NotificationType
from onyx.db.avatar import approve_permission_request
from onyx.db.avatar import deny_permission_request
from onyx.db.avatar import get_avatar_by_user_id
from onyx.db.avatar import get_pending_requests_for_avatar_owner
from onyx.db.avatar import get_permission_request_by_id
from onyx.db.avatar import get_permission_requests_by_requester
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AvatarPermissionRequestStatus
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.server.features.avatar.models import PermissionRequestApproveResponse
from onyx.server.features.avatar.models import PermissionRequestDenyRequest
from onyx.server.features.avatar.models import PermissionRequestSnapshot
from onyx.utils.logger import setup_logger


logger = setup_logger()

router = APIRouter(prefix="/avatar/permissions")


@router.get("/incoming")
def get_incoming_permission_requests(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[PermissionRequestSnapshot]:
    """Get all pending permission requests for the current user's avatar."""
    requests = get_pending_requests_for_avatar_owner(user.id, db_session)

    # Get the user's avatar to check show_query_in_request setting
    avatar = get_avatar_by_user_id(user.id, db_session)
    show_query = avatar.show_query_in_request if avatar else True

    return [
        PermissionRequestSnapshot.from_model(req, show_query=show_query)
        for req in requests
    ]


@router.get("/outgoing")
def get_outgoing_permission_requests(
    status: AvatarPermissionRequestStatus | None = None,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[PermissionRequestSnapshot]:
    """Get all permission requests made by the current user."""
    requests = get_permission_requests_by_requester(user.id, db_session, status=status)
    return [
        PermissionRequestSnapshot.from_model(req, show_query=True) for req in requests
    ]


@router.get("/{request_id}")
def get_permission_request(
    request_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> PermissionRequestSnapshot:
    """Get a specific permission request."""
    request = get_permission_request_by_id(request_id, db_session)
    if not request:
        raise HTTPException(status_code=404, detail="Permission request not found")

    # User can view if they are the requester or the avatar owner
    is_requester = request.requester_id == user.id
    is_avatar_owner = request.avatar.user_id == user.id

    if not is_requester and not is_avatar_owner:
        raise HTTPException(status_code=403, detail="Access denied")

    # Show query to requester, but respect avatar owner's preference
    show_query = is_requester or request.avatar.show_query_in_request

    return PermissionRequestSnapshot.from_model(request, show_query=show_query)


@router.post("/{request_id}/approve")
def approve_request(
    request_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> PermissionRequestApproveResponse:
    """Approve a permission request."""
    request = get_permission_request_by_id(request_id, db_session)
    if not request:
        raise HTTPException(status_code=404, detail="Permission request not found")

    # Only the avatar owner can approve
    if request.avatar.user_id != user.id:
        raise HTTPException(
            status_code=403, detail="Only the avatar owner can approve requests"
        )

    if request.status != AvatarPermissionRequestStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Request is already {request.status.value}",
        )

    approved_request = approve_permission_request(request_id, db_session)
    if not approved_request:
        raise HTTPException(status_code=500, detail="Failed to approve request")

    # Notify the requester
    create_notification(
        user_id=request.requester_id,
        notif_type=NotificationType.AVATAR_REQUEST_APPROVED,
        db_session=db_session,
        additional_data={"request_id": request_id, "avatar_id": request.avatar_id},
    )

    db_session.commit()

    return PermissionRequestApproveResponse(
        request_id=request_id,
        status=AvatarPermissionRequestStatus.APPROVED,
        answer=approved_request.cached_answer,
        source_document_ids=approved_request.cached_search_doc_ids,
    )


@router.post("/{request_id}/deny")
def deny_request(
    request_id: int,
    deny_request_body: PermissionRequestDenyRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> PermissionRequestSnapshot:
    """Deny a permission request."""
    request = get_permission_request_by_id(request_id, db_session)
    if not request:
        raise HTTPException(status_code=404, detail="Permission request not found")

    # Only the avatar owner can deny
    if request.avatar.user_id != user.id:
        raise HTTPException(
            status_code=403, detail="Only the avatar owner can deny requests"
        )

    if request.status != AvatarPermissionRequestStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Request is already {request.status.value}",
        )

    denied_request = deny_permission_request(
        request_id,
        db_session,
        denial_reason=deny_request_body.denial_reason,
    )
    if not denied_request:
        raise HTTPException(status_code=500, detail="Failed to deny request")

    # Notify the requester
    create_notification(
        user_id=request.requester_id,
        notif_type=NotificationType.AVATAR_REQUEST_DENIED,
        db_session=db_session,
        additional_data={
            "request_id": request_id,
            "avatar_id": request.avatar_id,
            "denial_reason": deny_request_body.denial_reason,
        },
    )

    db_session.commit()

    return PermissionRequestSnapshot.from_model(denied_request, show_query=True)
