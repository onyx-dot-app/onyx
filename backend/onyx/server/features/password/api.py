from fastapi import APIRouter, Depends, Request
from fastapi_users.exceptions import InvalidPasswordException
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.users import (
    User,
    UserManager,
    get_session_token_from_request,
    get_user_manager,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.users import get_user_by_email
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.password.models import (
    ChangePasswordRequest,
    UserResetRequest,
    UserResetResponse,
)

router = APIRouter(prefix="/password")


@router.post("/change-password")
async def change_my_password(
    form_data: ChangePasswordRequest,
    request: Request,
    user_manager: UserManager = Depends(get_user_manager),
    current_user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> None:
    """
    Change the password for the current user and sign out their other sessions.
    """
    try:
        await user_manager.change_password_if_old_matches(
            user=current_user,
            old_password=form_data.old_password,
            new_password=form_data.new_password,
            keep_token=get_session_token_from_request(request),
        )
    except InvalidPasswordException as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e.reason))


@router.post("/reset_password")
async def admin_reset_user_password(
    user_reset_request: UserResetRequest,
    user_manager: UserManager = Depends(get_user_manager),
    db_session: Session = Depends(get_session),
    admin_user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> UserResetResponse:
    """
    Reset the password for a user (admin only) and sign out all of their sessions.
    """
    user = get_user_by_email(user_reset_request.user_email, db_session)
    if not user:
        raise OnyxError(OnyxErrorCode.USER_NOT_FOUND, "User not found")
    if user.id == admin_user.id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "You cannot reset your own password here. Use the change-password flow instead.",
        )
    new_password = await user_manager.reset_password_as_admin(user.id)
    return UserResetResponse(
        user_id=str(user.id),
        new_password=new_password,
    )
