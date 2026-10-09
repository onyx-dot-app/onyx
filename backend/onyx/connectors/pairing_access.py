"""The access-type rules a pairing must meet, for any flow that sets a pair's
access type or data-access groups."""

from sqlalchemy.orm import Session

from onyx.auth.scoped_permissions import get_visible_user_group_ids
from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.store import get_security_settings
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


def validate_pairing_access(
    db_session: Session,
    *,
    user: User,
    source: DocumentSource,
    access_type: AccessType,
    data_access_group_ids: list[int] | None,
) -> None:
    """Raises ``OnyxError`` if ``user`` cannot pair a ``source`` connector with
    this access type and these data-access groups. These rules do not include
    the GATE 2 scope checks.

    Raises:
        OnyxError: FEATURE_NOT_AVAILABLE when group restrictions are turned
            off for a restricted pair, or when the plan does not include
            permission sync. INVALID_INPUT when a restricted pair has no
            data-access group, when data-access groups are set on an access
            type that does not use them, or when the source does not support
            permission sync. INSUFFICIENT_PERMISSIONS when the user cannot see
            a data-access group.
    """
    if access_type == AccessType.SYNC_RESTRICTED:
        if not get_security_settings().allow_connector_group_restrictions:
            raise OnyxError(
                OnyxErrorCode.FEATURE_NOT_AVAILABLE,
                "Group restrictions on permission-synced connectors are turned off "
                "for this workspace.",
            )
        if not data_access_group_ids:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "A restricted connector needs at least one data-access group.",
            )

    if data_access_group_ids:
        if access_type not in AccessType.data_access_types():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Data-access groups can only be set on private or restricted "
                "connectors.",
            )
        visible_group_ids = get_visible_user_group_ids(user, db_session)
        if visible_group_ids is not None and not visible_group_ids.issuperset(
            data_access_group_ids
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "You can't give data access to groups you can't see.",
            )

    if not access_type.is_perm_synced():
        return
    fetch_ee_implementation_or_noop(
        "onyx.utils.tier",
        "require_business_tier_for_sync_access",
        noop_return_value=None,
    )(access_type)
    if not fetch_ee_implementation_or_noop(
        "onyx.external_permissions.sync_params",
        "check_if_valid_sync_source",
        noop_return_value=True,
    )(source):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Connector of type {source} does not support permission sync",
        )
