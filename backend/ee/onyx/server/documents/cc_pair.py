from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    try_creating_permissions_sync_task,
)
from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    try_creating_external_group_sync_task,
)
from ee.onyx.db.cc_pair_data_access import (
    assert_restricted_cc_pairs_keep_a_group,
    fetch_data_access_groups_for_cc_pair,
    set_cc_pair_data_access_groups__no_commit,
)
from ee.onyx.db.connector_manage_access import (
    fetch_groups_with_global_permission,
    fetch_manage_roles_for_cc_pair,
    lock_cc_pairs_for_manage_access__no_commit,
)
from ee.onyx.db.user_group import fetch_user_groups
from ee.onyx.server.documents.manage_access import (
    CCPairManageAccessRow,
    CCPairManageAccessUpdateRequest,
    apply_manage_access_change__no_commit,
    fixed_manage_access_rows,
)
from ee.onyx.server.documents.models import (
    CCPairDataAccess,
    CCPairDataAccessUpdateRequest,
)
from ee.onyx.server.user_group.models import MinimalUserGroupSnapshot
from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import get_visible_user_group_ids
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_connector_credential_pair_from_id_for_user,
    verify_user_has_access_to_cc_pair,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType, ConnectorManageRole, Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import manage_access_by_group
from onyx.server.models import StatusResponse
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
router = APIRouter(prefix="/manage")


@router.get("/admin/cc-pair/{cc_pair_id}/sync-permissions")
def get_cc_pair_latest_sync(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> datetime | None:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.READ,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user's permissions",
        )

    return cc_pair.last_time_perm_sync


@router.post("/admin/cc-pair/{cc_pair_id}/sync-permissions")
def sync_cc_pair(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> StatusResponse[None]:
    """Triggers permissions sync on a particular cc_pair immediately"""
    tenant_id = get_current_tenant_id()

    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.OPERATE,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    r = get_redis_client()

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if redis_connector.permissions.fenced:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Permissions sync task already in progress.",
        )

    logger.info(
        "Permissions sync cc_pair=%s connector_id=%s credential_id=%s %s connector.",
        cc_pair_id,
        cc_pair.connector_id,
        cc_pair.credential_id,
        cc_pair.connector.name,
    )
    payload_id = try_creating_permissions_sync_task(
        client_app, cc_pair_id, r, tenant_id
    )
    if not payload_id:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Permissions sync task creation failed.",
        )

    logger.info("Permissions sync queued: cc_pair=%s id=%s", cc_pair_id, payload_id)

    return StatusResponse(
        success=True,
        message="Successfully created the permissions sync task.",
    )


@router.get("/admin/cc-pair/{cc_pair_id}/sync-groups")
def get_cc_pair_latest_group_sync(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> datetime | None:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.READ,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user's permissions",
        )

    return cc_pair.last_time_external_group_sync


@router.post("/admin/cc-pair/{cc_pair_id}/sync-groups")
def sync_cc_pair_groups(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> StatusResponse[None]:
    """Triggers group sync on a particular cc_pair immediately"""
    tenant_id = get_current_tenant_id()

    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.OPERATE,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    r = get_redis_client()

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if redis_connector.external_group_sync.fenced:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "External group sync task already in progress.",
        )

    logger.info(
        "External group sync cc_pair=%s connector_id=%s credential_id=%s %s connector.",
        cc_pair_id,
        cc_pair.connector_id,
        cc_pair.credential_id,
        cc_pair.connector.name,
    )
    payload_id = try_creating_external_group_sync_task(
        client_app, cc_pair_id, r, tenant_id
    )
    if not payload_id:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "External group sync task creation failed.",
        )

    logger.info("External group sync queued: cc_pair=%s id=%s", cc_pair_id, payload_id)

    return StatusResponse(
        success=True,
        message="Successfully created the external group sync task.",
    )


def _to_cc_pair_data_access(
    db_session: Session, cc_pair_id: int, visible_group_ids: set[int] | None
) -> CCPairDataAccess:
    return CCPairDataAccess(
        groups=[
            MinimalUserGroupSnapshot.from_model(group)
            for group in fetch_data_access_groups_for_cc_pair(db_session, cc_pair_id)
            if visible_group_ids is None or group.id in visible_group_ids
        ]
    )


@router.get("/admin/cc-pair/{cc_pair_id}/data-access")
def get_cc_pair_data_access(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CCPairDataAccess:
    """The pair's data-access groups that the caller can see."""
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.READ,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user's permissions",
        )
    return _to_cc_pair_data_access(
        db_session, cc_pair_id, get_visible_user_group_ids(user, db_session)
    )


@router.put("/admin/cc-pair/{cc_pair_id}/data-access")
def set_cc_pair_data_access(
    cc_pair_id: int,
    request: CCPairDataAccessUpdateRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CCPairDataAccess:
    """Sets the groups whose members may read the pair's documents. Search
    applies the change at once; the documents' group: entries follow through
    metadata sync. Current groups the caller can't see are kept."""
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.EDIT,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )
    if cc_pair.access_type not in AccessType.data_access_types():
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Data-access groups can only be set on private or restricted connectors.",
        )

    visible_group_ids = get_visible_user_group_ids(user, db_session)
    set_cc_pair_data_access_groups__no_commit(
        db_session,
        cc_pair_id=cc_pair_id,
        requested_group_ids=set(request.group_ids),
        visible_group_ids=visible_group_ids,
    )
    assert_restricted_cc_pairs_keep_a_group(db_session, [cc_pair_id])
    db_session.commit()
    return _to_cc_pair_data_access(db_session, cc_pair_id, visible_group_ids)


def _manage_access_rows(
    db_session: Session, cc_pair_id: int, visible_group_ids: set[int] | None
) -> list[CCPairManageAccessRow]:
    """The fixed rows, then the stored rows of groups the caller can see
    (``visible_group_ids``, None: all). A stored row of a group that is also
    fixed is left out: the fixed Editor row already covers it."""
    fixed_rows = fixed_manage_access_rows(db_session)
    fixed_group_ids = {row.group_id for row in fixed_rows}
    roles = fetch_manage_roles_for_cc_pair(db_session, cc_pair_id)
    shown_group_ids = {
        group_id
        for group_id in roles.keys() - fixed_group_ids
        if visible_group_ids is None or group_id in visible_group_ids
    }
    groups = fetch_user_groups(
        db_session, only_up_to_date=False, restrict_to_group_ids=shown_group_ids
    )
    return fixed_rows + [
        CCPairManageAccessRow(
            group_id=group.id,
            group_name=group.name,
            role=roles[group.id],
            is_fixed=False,
        )
        for group in sorted(groups, key=lambda group: group.id)
    ]


@router.get("/admin/cc-pair/{cc_pair_id}/manage-access")
def get_cc_pair_manage_access(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[CCPairManageAccessRow]:
    """The fixed rows (global MANAGE_CONNECTORS groups) first, then the stored ones."""
    # GATE 2: who manages a pair is management data, so the caller must operate it.
    if not verify_user_has_access_to_cc_pair(
        cc_pair_id, db_session, user, CCPairAccessLevel.OPERATE
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user's permissions",
        )
    return _manage_access_rows(
        db_session, cc_pair_id, get_visible_user_group_ids(user, db_session)
    )


@router.put("/admin/cc-pair/{cc_pair_id}/manage-access")
def set_cc_pair_manage_access(
    cc_pair_id: int,
    request: CCPairManageAccessUpdateRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[CCPairManageAccessRow]:
    """Replace the pair's stored rows. Fixed rows are not stored, so they stay."""
    # GATE 2: only an Editor changes who manages the pair. Checked before the
    # lock, so a missing id and one the caller cannot edit get the same answer.
    if not verify_user_has_access_to_cc_pair(
        cc_pair_id, db_session, user, CCPairAccessLevel.EDIT
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Group managers can only act on connectors where they are an Editor.",
        )
    if not lock_cc_pairs_for_manage_access__no_commit(db_session, [cc_pair_id]):
        raise OnyxError(OnyxErrorCode.CONNECTOR_NOT_FOUND, "CC Pair not found")

    requested = manage_access_by_group(request.manage_access)
    # GET hides a stored row of a group that later got a global grant, so the
    # request cannot list it. Keep that row: it applies again if the grant goes.
    fixed_group_ids = {
        group.id
        for group in fetch_groups_with_global_permission(
            db_session, Permission.MANAGE_CONNECTORS
        )
    }
    apply_manage_access_change__no_commit(
        db_session,
        user,
        current={
            (group_id, cc_pair_id): role
            for group_id, role in fetch_manage_roles_for_cc_pair(
                db_session, cc_pair_id
            ).items()
            if group_id not in fixed_group_ids
        },
        requested={
            (group_id, cc_pair_id): role for group_id, role in requested.items()
        },
    )
    db_session.commit()

    emit_audit_event(
        AuditAction.CC_PAIR_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="cc_pair",
        resource_id=cc_pair_id,
        extra={
            "manage_access": {
                str(group_id): role.value for group_id, role in requested.items()
            }
        },
    )
    return _manage_access_rows(
        db_session, cc_pair_id, get_visible_user_group_ids(user, db_session)
    )


@router.get("/admin/manage-access-prefill")
def get_manage_access_prefill(
    data_access: list[int] = Query(default=[]),
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[CCPairManageAccessRow]:
    """Starting manage access for the create form: groups with global Manage Connectors
    are fixed Editors, and the chosen data-access groups become Operators."""
    fixed_rows = fixed_manage_access_rows(db_session)
    fixed_group_ids = {row.group_id for row in fixed_rows}
    visible_group_ids = get_visible_user_group_ids(user, db_session)
    operator_group_ids = {
        group_id
        for group_id in data_access
        if group_id not in fixed_group_ids
        and (visible_group_ids is None or group_id in visible_group_ids)
    }
    operator_groups = fetch_user_groups(
        db_session,
        only_up_to_date=False,
        include_default=False,
        restrict_to_group_ids=operator_group_ids,
    )
    return fixed_rows + [
        CCPairManageAccessRow(
            group_id=group.id,
            group_name=group.name,
            role=ConnectorManageRole.OPERATOR,
            is_fixed=False,
        )
        for group in sorted(operator_groups, key=lambda group: group.id)
    ]
