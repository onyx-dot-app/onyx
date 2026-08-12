"""Membership query for groups-only incognito availability."""

from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from onyx.db.models import User__UserGroup, UserGroup


def user_in_incognito_enabled_group(db_session: Session, user_id: UUID) -> bool:
    """Whether any of the user's groups has its incognito flag set."""
    stmt = select(
        exists().where(
            User__UserGroup.user_id == user_id,
            User__UserGroup.user_group_id == UserGroup.id,
            UserGroup.incognito_enabled.is_(True),
        )
    )
    return bool(db_session.execute(stmt).scalar())
