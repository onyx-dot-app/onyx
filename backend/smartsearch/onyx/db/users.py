from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.db.models import User, User__UserGroup


async def fetch_all_users(
    db_session: AsyncSession
) -> Sequence[User]:
    query = select(User)
    result = await db_session.scalars(query)
    return result.unique().all()


async def fetch_user_by_my_groups(
    user: User,
    db_session: AsyncSession
) -> Sequence[User]:
    user_groups_subquery = select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id
    )

    query = (
        select(User)
        .join(User__UserGroup, User__UserGroup.user_id == User.id)
        .where(User__UserGroup.user_group_id.in_(user_groups_subquery))
    )

    result = await db_session.scalars(query)
    return result.unique().all()