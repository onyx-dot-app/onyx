from typing import Sequence
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from smartsearch.onyx.server.users.models import MinimalUsersSnapshot
from smartsearch.onyx.db.users import fetch_all_users, fetch_user_by_my_groups
from onyx.auth.users import current_user
from onyx.db.engine import get_async_session
from onyx.db.models import User, UserRole
from onyx.utils.logger import setup_logger


logger = setup_logger()


router = APIRouter(
    prefix="/users",
    tags=["Управление пользователями"]
)


@router.get(
    path="/by-my-groups",
    summary="Получение списка пользователей в зависимости от роли",
    description="""
        Администраторы получают полный список пользователей.
        Кураторы и обычные пользователи получают только тех пользователей,
        которые состоят в тех же группах, что и сам пользователь.
    """,
    response_model=list[MinimalUsersSnapshot]
)
async def list_users_by_my_groups_router(
    user: User = Depends(current_user),
    db_session: AsyncSession = Depends(get_async_session),
) -> Sequence[User]:
    """
    Получение списка пользователей.

    Администраторы получают полный список пользователей.
    Кураторы и обычные пользователи получают только тех пользователей,
    которые состоят в тех же группах, что и сам пользователь.

    Returns:
        Список пользователей в соответствии с правами доступа
    """
    if user.role == UserRole.ADMIN:
        users = await fetch_all_users(db_session=db_session)
    else:
        users = await fetch_user_by_my_groups(
            user=user,
            db_session=db_session,
        )

    return users