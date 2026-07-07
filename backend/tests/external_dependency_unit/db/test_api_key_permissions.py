"""Editing or rotating a key recomputes its permissions: legacy LIMITED
keys with a blank grant are repaired, and healthy keys keep the
permissions they already had."""

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


def _get_key_user(db_session: Session, user_id: UUID) -> User:
    user = db_session.scalar(
        select(User).where(User.id == user_id)  # ty: ignore[invalid-argument-type]
    )
    assert user is not None
    return user


def _blank_permissions(db_session: Session, user_id: UUID) -> User:
    user = _get_key_user(db_session, user_id)
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


def test_update_preserves_limited_key_permissions(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session,
        APIKeyArgs(name="limited-rename", role=UserRole.LIMITED),
        user_id=None,
    )
    user = _get_key_user(db_session, descriptor.user_id)
    assert user.effective_permissions == ["write:chat"]

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="limited-renamed", role=UserRole.LIMITED),
    )

    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    remove_api_key(db_session, descriptor.api_key_id)


def test_update_preserves_basic_key_permissions(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session, APIKeyArgs(name="basic-rename", role=UserRole.BASIC), user_id=None
    )
    user = _get_key_user(db_session, descriptor.user_id)
    perms_before = list(user.effective_permissions)
    assert perms_before

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="basic-renamed", role=UserRole.BASIC),
    )

    db_session.refresh(user)
    assert user.effective_permissions == perms_before

    remove_api_key(db_session, descriptor.api_key_id)


def test_update_role_change_swaps_permission_source(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session, APIKeyArgs(name="role-swap", role=UserRole.BASIC), user_id=None
    )
    user = _get_key_user(db_session, descriptor.user_id)
    basic_perms = list(user.effective_permissions)
    assert basic_perms

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="role-swap", role=UserRole.LIMITED),
    )
    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="role-swap", role=UserRole.BASIC),
    )
    db_session.refresh(user)
    assert user.effective_permissions == basic_perms

    remove_api_key(db_session, descriptor.api_key_id)


def test_regenerate_preserves_basic_key_permissions(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session, APIKeyArgs(name="basic-regen", role=UserRole.BASIC), user_id=None
    )
    user = _get_key_user(db_session, descriptor.user_id)
    perms_before = list(user.effective_permissions)
    assert perms_before

    regenerate_api_key(db_session, descriptor.api_key_id)

    db_session.refresh(user)
    assert user.effective_permissions == perms_before

    remove_api_key(db_session, descriptor.api_key_id)
