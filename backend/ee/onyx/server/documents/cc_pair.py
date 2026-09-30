from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    try_creating_permissions_sync_task,
)
from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    try_creating_external_group_sync_task,
)
from ee.onyx.db.cc_pair_data_access import (
    fetch_data_access_groups_for_cc_pair,
    set_cc_pair_data_access_groups__no_commit,
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
    get_connector_credential_pair_from_id_for_user,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType, Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.server.models import StatusResponse
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
        get_editable=False,
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
        get_editable=True,
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
        get_editable=False,
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
        get_editable=True,
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
        get_editable=False,
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
        get_editable=True,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )
    if cc_pair.access_type != AccessType.PRIVATE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Data-access groups can only be set on private connectors.",
        )

    visible_group_ids = get_visible_user_group_ids(user, db_session)
    set_cc_pair_data_access_groups__no_commit(
        db_session,
        cc_pair_id=cc_pair_id,
        requested_group_ids=set(request.group_ids),
        visible_group_ids=visible_group_ids,
    )
    db_session.commit()
    return _to_cc_pair_data_access(db_session, cc_pair_id, visible_group_ids)
