"""Editing or rotating a LIMITED key re-asserts its chat scope, repairing
legacy keys created before the grant existed."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.api_key import insert_api_key
from onyx.db.api_key import regenerate_api_key
from onyx.db.api_key import remove_api_key
from onyx.db.api_key import update_api_key
from onyx.db.models import User
from onyx.server.api_key.models import APIKeyArgs


def _blank_permissions(db_session: Session, user_id: UUID) -> User:
    user = db_session.scalar(
        select(User).where(User.id == user_id)  # ty: ignore[invalid-argument-type]
    )
    assert user is not None
    user.effective_permissions = []
    db_session.commit()
    return user


def test_update_repairs_legacy_limited_key(db_session: Session) -> None:
    args = APIKeyArgs(name="legacy-limited-update", role=UserRole.LIMITED)
    descriptor = insert_api_key(db_session, args, user_id=None)
    user = _blank_permissions(db_session, descriptor.user_id)

    update_api_key(db_session, descriptor.api_key_id, args)

    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    remove_api_key(db_session, descriptor.api_key_id)


def test_regenerate_repairs_legacy_limited_key(db_session: Session) -> None:
    args = APIKeyArgs(name="legacy-limited-regen", role=UserRole.LIMITED)
    descriptor = insert_api_key(db_session, args, user_id=None)
    user = _blank_permissions(db_session, descriptor.user_id)

    regenerate_api_key(db_session, descriptor.api_key_id)

    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    remove_api_key(db_session, descriptor.api_key_id)
