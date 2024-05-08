from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy import UUID_ID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from danswer.auth.schemas import UserRead
from danswer.auth.schemas import UserRole
from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.auth.users import get_display_email
from danswer.auth.users import optional_user
from danswer.db.engine import get_session
from danswer.db.engine import get_sqlalchemy_async_engine
from danswer.db.models import User
from danswer.db.users import list_users
from danswer.server.manage.models import UserByEmail
from danswer.server.manage.models import UserInfo
from danswer.server.manage.models import UserRoleResponse

router = APIRouter(prefix="/manage")


@router.patch("/promote-user-to-admin")
async def promote_admin(
    user_email: UserByEmail, user: User = Depends(current_admin_user)
) -> None:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with AsyncSession(get_sqlalchemy_async_engine()) as asession:
        user_db = SQLAlchemyUserDatabase[User, UUID_ID](asession, User)
        user_to_promote = await user_db.get_by_email(user_email.user_email)
        if not user_to_promote:
            raise HTTPException(status_code=404, detail="User not found")
        user_to_promote.role = UserRole.ADMIN
        asession.add(user_to_promote)
        await asession.commit()
    return


@router.get("/users")
def list_all_users(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserRead]:
    users = list_users(db_session)
    return [UserRead.from_orm(user) for user in users]


@router.get("/get-user-role", response_model=UserRoleResponse)
async def get_user_role(user: User = Depends(current_user)) -> UserRoleResponse:
    if user is None:
        raise ValueError("Invalid or missing user.")
    return UserRoleResponse(role=user.role)


@router.get("/me")
def verify_user_logged_in(user: User | None = Depends(optional_user)) -> UserInfo:
    # NOTE: this does not use `current_user` / `current_admin_user` because we don't want
    # to enforce user verification here - the frontend always wants to get the info about
    # the current user regardless of if they are currently verified
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User Not Authenticated"
        )

    return UserInfo(
        id=str(user.id),
        email=get_display_email(user.email, space_less=True),
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_verified=user.is_verified,
        role=user.role,
    )
