"""Editing or rotating a key recomputes its permissions: group-less keys with
a blank grant are repaired, and healthy keys keep the permissions they
already had."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.api_key import (
    insert_api_key,
    regenerate_api_key,
    remove_api_key,
    update_api_key,
)
from onyx.db.models import User, UserGroup
from onyx.server.api_key.models import APIKeyArgs


def _basic_group_id(db_session: Session) -> int:
    """The seeded Basic default group — a key in it draws real grants, unlike a
    group-less key which falls back to the service-account chat scope."""
    group = db_session.scalar(
        select(UserGroup).where(
            UserGroup.name == "Basic", UserGroup.is_default.is_(True)
        )
    )
    assert group is not None
    return group.id


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
    args = APIKeyArgs(name="legacy-limited-update")
    descriptor = insert_api_key(db_session, args, user_id=None)
    user = _blank_permissions(db_session, descriptor.user_id)

    update_api_key(db_session, descriptor.api_key_id, args)

    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    remove_api_key(db_session, descriptor.api_key_id)


def test_regenerate_repairs_legacy_limited_key(db_session: Session) -> None:
    args = APIKeyArgs(name="legacy-limited-regen")
    descriptor = insert_api_key(db_session, args, user_id=None)
    user = _blank_permissions(db_session, descriptor.user_id)

    regenerate_api_key(db_session, descriptor.api_key_id)

    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    remove_api_key(db_session, descriptor.api_key_id)


def test_update_preserves_limited_key_permissions(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session,
        APIKeyArgs(name="limited-rename"),
        user_id=None,
    )
    user = _get_key_user(db_session, descriptor.user_id)
    assert user.effective_permissions == ["write:chat"]

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="limited-renamed"),
    )

    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    remove_api_key(db_session, descriptor.api_key_id)


def test_update_preserves_basic_key_permissions(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session,
        APIKeyArgs(name="basic-rename", group_ids=[_basic_group_id(db_session)]),
        user_id=None,
    )
    user = _get_key_user(db_session, descriptor.user_id)
    perms_before = list(user.effective_permissions)
    assert perms_before

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="basic-renamed", group_ids=[_basic_group_id(db_session)]),
    )

    db_session.refresh(user)
    assert user.effective_permissions == perms_before

    remove_api_key(db_session, descriptor.api_key_id)


def test_update_role_change_swaps_permission_source(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session,
        APIKeyArgs(name="role-swap", group_ids=[_basic_group_id(db_session)]),
        user_id=None,
    )
    user = _get_key_user(db_session, descriptor.user_id)
    basic_perms = list(user.effective_permissions)
    assert basic_perms

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="role-swap"),
    )
    db_session.refresh(user)
    assert user.effective_permissions == ["write:chat"]

    update_api_key(
        db_session,
        descriptor.api_key_id,
        APIKeyArgs(name="role-swap", group_ids=[_basic_group_id(db_session)]),
    )
    db_session.refresh(user)
    assert user.effective_permissions == basic_perms

    remove_api_key(db_session, descriptor.api_key_id)


def test_regenerate_preserves_basic_key_permissions(db_session: Session) -> None:
    descriptor = insert_api_key(
        db_session,
        APIKeyArgs(name="basic-regen", group_ids=[_basic_group_id(db_session)]),
        user_id=None,
    )
    user = _get_key_user(db_session, descriptor.user_id)
    perms_before = list(user.effective_permissions)
    assert perms_before

    regenerate_api_key(db_session, descriptor.api_key_id)

    db_session.refresh(user)
    assert user.effective_permissions == perms_before

    remove_api_key(db_session, descriptor.api_key_id)
