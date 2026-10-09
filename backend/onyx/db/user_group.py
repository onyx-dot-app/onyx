"""Invariants for the seeded default groups (Admin/Basic).

A default group holds members and nothing else: no connectors, document sets, agents,
skills, providers or limits, and its name and permission grant are fixed at seed time.

Lives in Community Edition even though group management is Enterprise: the groups are
seeded by a core migration and the resource-sharing paths that must refuse them are core
code. ``ee/onyx/db/user_group.py`` holds the management operations.
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import UserGroup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def assert_group_config_is_editable(
    db_session: Session, user_group_id: int, action: str
) -> None:
    """Membership is the only thing a default group has, so every other write is refused.
    ``action`` completes "Cannot {action} a default system group.". A missing group falls
    through to the caller's own NOT_FOUND."""
    assert_groups_config_are_editable(db_session, [user_group_id], action)


def assert_groups_config_are_editable(
    db_session: Session, user_group_ids: Collection[int], action: str
) -> None:
    """Batch form for a caller holding several ids — one query rather than one per id."""
    if not user_group_ids:
        return

    is_default_present = db_session.scalar(
        select(UserGroup.id)
        .where(
            UserGroup.id.in_(user_group_ids),
            UserGroup.is_default.is_(True),
        )
        .limit(1)
    )
    if is_default_present is not None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, f"Cannot {action} a default system group."
        )


def assert_not_shared_with_default_group(
    db_session: Session, group_ids: Collection[int]
) -> None:
    """Keep a default group empty of everything but members, from any resource's own side.
    Basic holds the whole org and Admin every admin, so sharing with one is really "make
    this public", which every resource already expresses with its own public flag."""
    if not group_ids:
        return

    default_names = db_session.scalars(
        select(UserGroup.name).where(
            UserGroup.id.in_(group_ids),
            UserGroup.is_default.is_(True),
        )
    ).all()
    if default_names:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Cannot share with the default system group(s): "
            + ", ".join(sorted(default_names))
            + ". Make the resource public instead.",
        )
