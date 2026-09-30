"""Manage access rows: which groups manage a cc-pair, and with which role.

Rows are written in place. They grant management only, so a change needs no
document sync and no ``is_current`` history.
"""

from collections import defaultdict
from collections.abc import Collection

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import fetch_user_groups
from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import ConnectorManageRole, Permission
from onyx.db.models import (
    ConnectorCredentialPair,
    PermissionGrant,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# (user_group_id, cc_pair_id)
ManageRowKey = tuple[int, int]


def lock_cc_pairs_for_manage_access__no_commit(
    db_session: Session, cc_pair_ids: Collection[int]
) -> set[int]:
    """Take the group-membership lock, then row-lock the pairs (in id order) and
    return the ids that exist. Every manage-row writer takes the membership lock
    before it reads the current rows, the legacy group PATCH included, so a
    concurrent write cannot slip between a check and its write."""
    lock_group_membership(db_session)
    if not cc_pair_ids:
        return set()
    return set(
        db_session.scalars(
            select(ConnectorCredentialPair.id)
            .where(ConnectorCredentialPair.id.in_(cc_pair_ids))
            .order_by(ConnectorCredentialPair.id)
            .with_for_update()
        )
    )


def fetch_manage_roles_for_cc_pair(
    db_session: Session, cc_pair_id: int
) -> dict[int, ConnectorManageRole]:
    """Group id → role, for the pair's live manage rows."""
    rows = db_session.execute(
        select(
            UserGroup__ConnectorCredentialPair.user_group_id,
            UserGroup__ConnectorCredentialPair.role,
        ).where(
            UserGroup__ConnectorCredentialPair.cc_pair_id == cc_pair_id,
            UserGroup__ConnectorCredentialPair.is_current.is_(True),
        )
    ).tuples()
    return dict(rows.all())


def fetch_managed_cc_pair_roles_for_group(
    db_session: Session, user_group_id: int
) -> dict[int, ConnectorManageRole]:
    """cc-pair id → role, for the group's live manage rows."""
    rows = db_session.execute(
        select(
            UserGroup__ConnectorCredentialPair.cc_pair_id,
            UserGroup__ConnectorCredentialPair.role,
        ).where(
            UserGroup__ConnectorCredentialPair.user_group_id == user_group_id,
            UserGroup__ConnectorCredentialPair.is_current.is_(True),
        )
    ).tuples()
    return dict(rows.all())


def fetch_groups_with_global_permission(
    db_session: Session, permission: Permission
) -> list[UserGroup]:
    """Groups whose own grants resolve to ``permission`` (the Admin group included).
    Their members hold it globally, so they manage every pair without a row."""
    grants_by_group: dict[int, set[str]] = defaultdict(set)
    for group_id, granted in db_session.execute(
        select(PermissionGrant.group_id, PermissionGrant.permission).where(
            PermissionGrant.is_deleted.is_(False)
        )
    ):
        grants_by_group[group_id].add(granted.value)
    group_ids = [
        group_id
        for group_id, granted in grants_by_group.items()
        if permission.value in resolve_effective_permissions(granted)
    ]
    groups = fetch_user_groups(
        db_session, only_up_to_date=False, restrict_to_group_ids=set(group_ids)
    )
    return sorted(groups, key=lambda group: group.id)


def assert_groups_have_no_global_manage_grant(
    db_session: Session, group_ids: Collection[int]
) -> None:
    """A group with a global MANAGE_CONNECTORS grant is a fixed Editor of every
    pair. A stored row for it would list the group twice, with two roles."""
    if not group_ids:
        return
    fixed_group_ids = {
        group.id
        for group in fetch_groups_with_global_permission(
            db_session, Permission.MANAGE_CONNECTORS
        )
    }
    if conflicting := sorted(fixed_group_ids.intersection(group_ids)):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"User group(s) {conflicting} manage every connector through a global "
            "Manage Connectors grant, so they can't get a connector role.",
        )


def write_manage_rows__no_commit(
    db_session: Session,
    upserts: dict[ManageRowKey, ConnectorManageRole],
    deletes: Collection[ManageRowKey],
) -> None:
    """Insert or re-role the ``upserts`` rows and drop the ``deletes`` rows, in place."""
    if upserts:
        stmt = insert(UserGroup__ConnectorCredentialPair).values(
            [
                {
                    "user_group_id": group_id,
                    "cc_pair_id": cc_pair_id,
                    "is_current": True,
                    "role": role,
                }
                for (group_id, cc_pair_id), role in upserts.items()
            ]
        )
        db_session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    UserGroup__ConnectorCredentialPair.user_group_id,
                    UserGroup__ConnectorCredentialPair.cc_pair_id,
                    UserGroup__ConnectorCredentialPair.is_current,
                ],
                set_={"role": stmt.excluded.role},
            )
        )
    if deletes:
        db_session.execute(
            delete(UserGroup__ConnectorCredentialPair).where(
                tuple_(
                    UserGroup__ConnectorCredentialPair.user_group_id,
                    UserGroup__ConnectorCredentialPair.cc_pair_id,
                ).in_(list(deletes)),
                UserGroup__ConnectorCredentialPair.is_current.is_(True),
            )
        )
