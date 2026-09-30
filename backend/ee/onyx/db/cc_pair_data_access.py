"""Data-access groups of cc-pairs (UserGroup__CCPairDataAccess).

For a PRIVATE pair, members of its data-access groups may read all its
documents. For a SYNC_RESTRICTED pair, they may read the documents their source
ACL allows. The rows are read at query time (the cc-pair access filter) and,
for PRIVATE pairs, at index time (the group: ACL entries). A write marks the
pair's documents for metadata sync, so the group: entries stay current.
"""

from collections.abc import Collection

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.document import mark_cc_pair_documents_for_sync__no_commit
from onyx.db.enums import AccessType
from onyx.db.models import (
    ConnectorCredentialPair,
    UserGroup,
    UserGroup__CCPairDataAccess,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def fetch_data_access_groups_for_cc_pair(
    db_session: Session, cc_pair_id: int
) -> list[UserGroup]:
    return list(
        db_session.scalars(
            select(UserGroup)
            .join(
                UserGroup__CCPairDataAccess,
                UserGroup__CCPairDataAccess.user_group_id == UserGroup.id,
            )
            .where(UserGroup__CCPairDataAccess.cc_pair_id == cc_pair_id)
            .order_by(UserGroup.name)
        )
    )


def fetch_data_access_cc_pair_ids_for_user_group(
    db_session: Session, user_group_id: int
) -> set[int]:
    return set(
        db_session.scalars(
            select(UserGroup__CCPairDataAccess.cc_pair_id).where(
                UserGroup__CCPairDataAccess.user_group_id == user_group_id
            )
        )
    )


def fetch_private_cc_pair_ids(
    db_session: Session, cc_pair_ids: Collection[int]
) -> set[int]:
    if not cc_pair_ids:
        return set()
    return set(
        db_session.scalars(
            select(ConnectorCredentialPair.id).where(
                ConnectorCredentialPair.id.in_(cc_pair_ids),
                ConnectorCredentialPair.access_type == AccessType.PRIVATE,
            )
        )
    )


def fetch_cc_pair_ids_with_data_access(
    db_session: Session, cc_pair_ids: Collection[int]
) -> set[int]:
    """The pairs of cc_pair_ids whose data-access groups decide who may read
    them (PRIVATE and SYNC_RESTRICTED)."""
    if not cc_pair_ids:
        return set()
    return set(
        db_session.scalars(
            select(ConnectorCredentialPair.id).where(
                ConnectorCredentialPair.id.in_(cc_pair_ids),
                ConnectorCredentialPair.access_type.in_(AccessType.data_access_types()),
            )
        )
    )


def assert_restricted_cc_pairs_keep_a_group(
    db_session: Session, cc_pair_ids: Collection[int]
) -> None:
    """A SYNC_RESTRICTED pair with no data-access group is visible to nobody,
    so a write must not remove its last group."""
    if not cc_pair_ids:
        return
    has_group = (
        select(UserGroup__CCPairDataAccess.cc_pair_id)
        .where(UserGroup__CCPairDataAccess.cc_pair_id == ConnectorCredentialPair.id)
        .exists()
    )
    ungrouped_ids = sorted(
        db_session.scalars(
            select(ConnectorCredentialPair.id).where(
                ConnectorCredentialPair.id.in_(cc_pair_ids),
                ConnectorCredentialPair.access_type == AccessType.SYNC_RESTRICTED,
                ~has_group,
            )
        )
    )
    if ungrouped_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A restricted connector needs at least one data-access group: "
            f"{ungrouped_ids}",
        )


def add_cc_pair_data_access__no_commit(
    db_session: Session,
    *,
    cc_pair_ids: Collection[int],
    user_group_ids: Collection[int],
) -> None:
    """Gives every group in user_group_ids data access to every pair in
    cc_pair_ids. Does not mark documents for sync."""
    if not cc_pair_ids or not user_group_ids:
        return
    db_session.execute(
        insert(UserGroup__CCPairDataAccess)
        .values(
            [
                {"cc_pair_id": cc_pair_id, "user_group_id": user_group_id}
                for cc_pair_id in cc_pair_ids
                for user_group_id in user_group_ids
            ]
        )
        .on_conflict_do_nothing()
    )


def remove_cc_pair_data_access__no_commit(
    db_session: Session,
    *,
    cc_pair_ids: Collection[int],
    user_group_ids: Collection[int],
) -> None:
    """Removes the data access of every group in user_group_ids to every pair
    in cc_pair_ids. Does not mark documents for sync."""
    if not cc_pair_ids or not user_group_ids:
        return
    db_session.execute(
        delete(UserGroup__CCPairDataAccess).where(
            UserGroup__CCPairDataAccess.cc_pair_id.in_(cc_pair_ids),
            UserGroup__CCPairDataAccess.user_group_id.in_(user_group_ids),
        )
    )


def _assert_groups_can_get_data_access(
    db_session: Session, user_group_ids: set[int]
) -> None:
    if not user_group_ids:
        return
    assert_not_shared_with_default_group(db_session, user_group_ids)
    found_group_ids = set(
        db_session.scalars(
            select(UserGroup.id).where(
                UserGroup.id.in_(user_group_ids),
                UserGroup.is_up_for_deletion.is_(False),
            )
        )
    )
    if missing_group_ids := user_group_ids - found_group_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"User group(s) not found: {sorted(missing_group_ids)}",
        )


def set_cc_pair_data_access_groups__no_commit(
    db_session: Session,
    cc_pair_id: int,
    requested_group_ids: set[int],
    visible_group_ids: set[int] | None,
) -> None:
    """Sets the data-access groups of a pair to requested_group_ids.

    visible_group_ids are the groups the caller can see (None: all groups).
    Current groups the caller cannot see stay, and adding a group the caller
    cannot see is refused."""
    current_group_ids = {
        group.id
        for group in fetch_data_access_groups_for_cc_pair(db_session, cc_pair_id)
    }
    final_group_ids = requested_group_ids
    if visible_group_ids is not None:
        if hidden_added := requested_group_ids - current_group_ids - visible_group_ids:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                f"You can't give data access to groups you can't see: {sorted(hidden_added)}",
            )
        final_group_ids = requested_group_ids | (current_group_ids - visible_group_ids)

    added_group_ids = final_group_ids - current_group_ids
    removed_group_ids = current_group_ids - final_group_ids
    if not added_group_ids and not removed_group_ids:
        return

    _assert_groups_can_get_data_access(db_session, added_group_ids)
    add_cc_pair_data_access__no_commit(
        db_session, cc_pair_ids=[cc_pair_id], user_group_ids=added_group_ids
    )
    remove_cc_pair_data_access__no_commit(
        db_session, cc_pair_ids=[cc_pair_id], user_group_ids=removed_group_ids
    )
    mark_cc_pair_documents_for_sync__no_commit(db_session, [cc_pair_id])


def apply_group_cc_pair_change_to_data_access__no_commit(
    db_session: Session,
    user_group_id: int,
    added_cc_pair_ids: Collection[int],
    removed_cc_pair_ids: Collection[int],
) -> None:
    """The group-side cc_pair_ids of the user-group API set manage access and,
    for PRIVATE pairs, data access together. Does not mark documents for sync:
    the user-group sync of the manage change re-syncs these pairs' documents."""
    add_cc_pair_data_access__no_commit(
        db_session,
        cc_pair_ids=fetch_private_cc_pair_ids(db_session, added_cc_pair_ids),
        user_group_ids=[user_group_id],
    )
    remove_cc_pair_data_access__no_commit(
        db_session,
        cc_pair_ids=fetch_private_cc_pair_ids(db_session, removed_cc_pair_ids),
        user_group_ids=[user_group_id],
    )
