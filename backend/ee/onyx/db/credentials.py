from collections.abc import Collection

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission
from onyx.db.models import (
    Credential,
    Credential__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.scoped_permissions import scoped_group_ids_subquery
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def _build_credential_group_access_clause(user: User) -> ColumnElement[bool]:
    """True for credentials shared with a group in which the user holds Manage
    Connectors: as a manager of the group, or as a member who holds the
    permission globally (group permissions). Default groups never count.

    NOTE: is imported in onyx.db.credentials by `fetch_versioned_implementation`.
    DO NOT REMOVE."""
    if has_global_permission(user, Permission.MANAGE_CONNECTORS):
        group_ids = (
            select(User__UserGroup.user_group_id)
            .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
            .where(
                User__UserGroup.user_id == user.id,
                UserGroup.is_default.is_(False),
            )
        )
    else:
        group_ids = scoped_group_ids_subquery(user)
    return (
        select(Credential__UserGroup.credential_id)
        .where(
            Credential__UserGroup.credential_id == Credential.id,
            Credential__UserGroup.user_group_id.in_(group_ids),
        )
        .correlate(Credential)
        .exists()
    )


def validate_credential_group_ids(
    db_session: Session, group_ids: Collection[int]
) -> None:
    """Raises ``OnyxError`` unless every group exists, is not being deleted and
    is not a default group.

    NOTE: is imported in onyx.db.credentials by `fetch_versioned_implementation`.
    DO NOT REMOVE."""
    if not group_ids:
        return
    assert_not_shared_with_default_group(db_session, group_ids)
    found_group_ids = set(
        db_session.scalars(
            select(UserGroup.id).where(
                UserGroup.id.in_(group_ids),
                UserGroup.is_up_for_deletion.is_(False),
            )
        )
    )
    if missing_group_ids := set(group_ids) - found_group_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"User group(s) not found: {sorted(missing_group_ids)}",
        )
