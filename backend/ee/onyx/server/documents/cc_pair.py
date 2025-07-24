from datetime import datetime
from http import HTTPStatus

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    try_creating_permissions_sync_task,
)
from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    try_creating_external_group_sync_task,
)
from onyx.auth.users import current_curator_or_admin_user
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id_for_user,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
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
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> datetime | None:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=False,
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400,
            detail="cc_pair not found for current user's permissions",
        )

    return cc_pair.last_time_perm_sync


@router.post("/admin/cc-pair/{cc_pair_id}/sync-permissions")
def sync_cc_pair(
    cc_pair_id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[None]:
    """Triggers permissions sync on a particular cc_pair immediately"""
    tenant_id = get_current_tenant_id()

    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=False,
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400,
            detail="Connection not found for current user's permissions",
        )

    r = get_redis_client()

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if redis_connector.permissions.fenced:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Permissions sync task already in progress.",
        )

    logger.info(
        f"Permissions sync cc_pair={cc_pair_id} "
        f"connector_id={cc_pair.connector_id} "
        f"credential_id={cc_pair.credential_id} "
        f"{cc_pair.connector.name} connector."
    )
    payload_id = try_creating_permissions_sync_task(
        client_app, cc_pair_id, r, tenant_id
    )
    if not payload_id:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Permissions sync task creation failed.",
        )

    logger.info(f"Permissions sync queued: cc_pair={cc_pair_id} id={payload_id}")

    return StatusResponse(
        success=True,
        message="Successfully created the permissions sync task.",
    )


@router.get("/admin/cc-pair/{cc_pair_id}/sync-groups")
def get_cc_pair_latest_group_sync(
    cc_pair_id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> datetime | None:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=False,
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400,
            detail="cc_pair not found for current user's permissions",
        )

    return cc_pair.last_time_external_group_sync


@router.post("/admin/cc-pair/{cc_pair_id}/sync-groups")
def sync_cc_pair_groups(
    cc_pair_id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[None]:
    """Triggers group sync on a particular cc_pair immediately"""
    tenant_id = get_current_tenant_id()

    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=False,
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400,
            detail="Connection not found for current user's permissions",
        )

    r = get_redis_client()

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if redis_connector.external_group_sync.fenced:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="External group sync task already in progress.",
        )

    logger.info(
        f"External group sync cc_pair={cc_pair_id} "
        f"connector_id={cc_pair.connector_id} "
        f"credential_id={cc_pair.credential_id} "
        f"{cc_pair.connector.name} connector."
    )
    payload_id = try_creating_external_group_sync_task(
        client_app, cc_pair_id, r, tenant_id
    )
    if not payload_id:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="External group sync task creation failed.",
        )

    logger.info(f"External group sync queued: cc_pair={cc_pair_id} id={payload_id}")

    return StatusResponse(
        success=True,
        message="Successfully created the external group sync task.",
    )
