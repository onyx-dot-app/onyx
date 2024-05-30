from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from danswer.auth.noauth_user import fetch_no_auth_user
from danswer.auth.noauth_user import set_no_auth_user_preferences
from danswer.auth.schemas import UserRead
from danswer.auth.schemas import UserRole
from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.auth.users import optional_user
from danswer.configs.app_configs import AUTH_TYPE
from danswer.configs.constants import AuthType
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.db.users import get_user_by_email
from danswer.db.users import list_users
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.server.manage.models import UserByEmail
from danswer.server.manage.models import UserInfo
from danswer.server.manage.models import UserRoleResponse
from danswer.server.models import MinimalUserSnapshot

router = APIRouter()


@router.patch("/manage/promote-user-to-admin")
def promote_admin(
    user_email: UserByEmail,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_to_promote = get_user_by_email(
        email=user_email.user_email, db_session=db_session
    )
    if not user_to_promote:
        raise HTTPException(status_code=404, detail="User not found")

    user_to_promote.role = UserRole.ADMIN
    db_session.add(user_to_promote)
    db_session.commit()


@router.patch("/manage/demote-admin-to-basic")
async def demote_admin(
    user_email: UserByEmail,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_to_demote = get_user_by_email(
        email=user_email.user_email, db_session=db_session
    )
    if not user_to_demote:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_demote.id == user.id:
        raise HTTPException(
            status_code=400, detail="Cannot demote yourself from admin role!"
        )

    user_to_demote.role = UserRole.BASIC
    db_session.add(user_to_demote)
    db_session.commit()


@router.get("/manage/users")
def list_all_users(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserRead]:
    users = list_users(db_session)
    return [UserRead.from_orm(user) for user in users]


"""Endpoints for all"""


@router.get("/users")
def list_all_users_basic_info(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[MinimalUserSnapshot]:
    users = list_users(db_session)
    return [MinimalUserSnapshot(id=user.id, email=user.email) for user in users]


@router.get("/get-user-role")
async def get_user_role(user: User = Depends(current_user)) -> UserRoleResponse:
    if user is None:
        raise ValueError("Invalid or missing user.")
    return UserRoleResponse(role=user.role)


@router.get("/me")
def verify_user_logged_in(
    user: User | None = Depends(optional_user),
) -> UserInfo:
    # NOTE: this does not use `current_user` / `current_admin_user` because we don't want
    # to enforce user verification here - the frontend always wants to get the info about
    # the current user regardless of if they are currently verified
    if user is None:
        # if auth type is disabled, return a dummy user with preferences from
        # the key-value store
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_dynamic_config_store()
            return fetch_no_auth_user(store)

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User Not Authenticated"
        )

    return UserInfo.from_model(user)


"""APIs to adjust user preferences"""


class ChosenAssistantsRequest(BaseModel):
    chosen_assistants: list[int]


@router.patch("/user/assistant-list")
def update_user_assistant_list(
    request: ChosenAssistantsRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    if user is None:
        if AUTH_TYPE == AuthType.DISABLED:
            store = get_dynamic_config_store()

            no_auth_user = fetch_no_auth_user(store)
            no_auth_user.preferences.chosen_assistants = request.chosen_assistants
            set_no_auth_user_preferences(store, no_auth_user.preferences)
            return
        else:
            raise RuntimeError("This should never happen")

    db_session.execute(
        update(User)
        .where(User.id == user.id)  # type: ignore
        .values(chosen_assistants=request.chosen_assistants)
    )
    db_session.commit()
