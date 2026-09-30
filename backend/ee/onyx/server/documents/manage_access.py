"""Manage access on cc-pairs, set from the pair side.

A change replaces the pair's (group, cc-pair) rows. Every row the change adds,
re-roles or removes needs a group the caller can see and a pair the caller is an
Editor of. Groups with a global MANAGE_CONNECTORS grant are not stored: they manage
every pair, so they show as fixed rows that no write can remove. The group-side route
keeps the group-edit authorization instead (see set_group_managed_cc_pairs).
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.connector_manage_access import (
    ManageRowKey,
    fetch_groups_with_global_permission,
    write_manage_rows__no_commit,
)
from ee.onyx.db.user_group import fetch_user_groups
from onyx.auth.scoped_permissions import get_visible_user_group_ids
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    verify_user_can_manage_all_cc_pairs,
)
from onyx.db.enums import ConnectorManageRole, Permission
from onyx.db.models import User
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.models import ManageAccessList


class CCPairManageAccessRow(BaseModel):
    group_id: int
    group_name: str
    role: ConnectorManageRole
    # Granted by a global MANAGE_CONNECTORS grant: not stored, cannot be removed.
    is_fixed: bool


class CCPairManageAccessUpdateRequest(BaseModel):
    manage_access: ManageAccessList


def fixed_manage_access_rows(db_session: Session) -> list[CCPairManageAccessRow]:
    return [
        CCPairManageAccessRow(
            group_id=group.id,
            group_name=group.name,
            role=ConnectorManageRole.EDITOR,
            is_fixed=True,
        )
        for group in fetch_groups_with_global_permission(
            db_session, Permission.MANAGE_CONNECTORS
        )
    ]


def apply_manage_access_change__no_commit(
    db_session: Session,
    user: User,
    current: dict[ManageRowKey, ConnectorManageRole],
    requested: dict[ManageRowKey, ConnectorManageRole],
) -> None:
    """Replace ``current`` with ``requested``. The caller locks the pairs first."""
    upserts = {
        key: role for key, role in requested.items() if current.get(key) is not role
    }
    deletes = current.keys() - requested.keys()
    touched = upserts.keys() | deletes
    if not touched:
        return

    visible_group_ids = get_visible_user_group_ids(user, db_session)
    touched_group_ids = {group_id for group_id, _ in touched}
    if visible_group_ids is not None and not touched_group_ids <= visible_group_ids:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Group managers can only act on groups they can see.",
        )
    if not verify_user_can_manage_all_cc_pairs(
        {cc_pair_id for _, cc_pair_id in touched},
        db_session,
        user,
        CCPairAccessLevel.EDIT,
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Group managers can only act on connectors where they are an Editor.",
        )

    added_group_ids = {group_id for group_id, _ in upserts.keys() - current.keys()}
    found_group_ids = {
        group.id
        for group in fetch_user_groups(
            db_session, only_up_to_date=False, restrict_to_group_ids=added_group_ids
        )
    }
    if missing := sorted(added_group_ids - found_group_ids):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"User group(s) {missing} not found")
    assert_not_shared_with_default_group(db_session, added_group_ids)

    write_manage_rows__no_commit(db_session, upserts=upserts, deletes=deletes)
