from datetime import datetime
from http import HTTPStatus

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.background.celery.celery_utils import get_deletion_attempt_snapshot
from onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    try_creating_permissions_sync_task,
)
from onyx.background.celery.tasks.external_group_syncing.tasks import (
    try_creating_external_group_sync_task,
)
from onyx.background.celery.tasks.pruning.tasks import (
    try_creating_prune_generator_task,
)
from onyx.background.celery.versioned_apps.primary import app as primary_app
from onyx.background.indexing.models import IndexAttemptErrorPydantic
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id_for_user,
)
from onyx.db.connector_credential_pair import remove_credential_from_connector
from onyx.db.connector_credential_pair import (
    update_connector_credential_pair_from_id,
)
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.document import get_documents_for_cc_pair
from onyx.db.engine import get_session
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.index_attempt import count_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import count_index_attempts_for_connector
from onyx.db.index_attempt import get_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.db.index_attempt import get_paginated_index_attempts_for_cc_pair_id
from onyx.db.models import SearchSettings
from onyx.db.models import User
from onyx.db.search_settings import get_active_search_settings_list
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CCPairFullInfo
from onyx.server.documents.models import CCPropertyUpdateRequest
from onyx.server.documents.models import CCStatusUpdateRequest
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.server.documents.models import ConnectorCredentialPairMetadata
from onyx.server.documents.models import DocumentSyncStatus
from onyx.server.documents.models import IndexAttemptSnapshot
from onyx.server.documents.models import PaginatedReturn
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
router = APIRouter(prefix="/manage")


@router.get("/admin/cc-pair/{cc_pair_id}/index-attempts")
def get_cc_pair_index_attempts(
    cc_pair_id: int,
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=1000),
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[IndexAttemptSnapshot]:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, get_editable=False
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400, detail="CC Pair not found for current user permissions"
        )
    total_count = count_index_attempts_for_connector(
        db_session=db_session,
        connector_id=cc_pair.connector_id,
    )
    index_attempts = get_paginated_index_attempts_for_cc_pair_id(
        db_session=db_session,
        connector_id=cc_pair.connector_id,
        page=page_num,
        page_size=page_size,
    )
    return PaginatedReturn(
        items=[
            IndexAttemptSnapshot.from_index_attempt_db_model(index_attempt)
            for index_attempt in index_attempts
        ],
        total_items=total_count,
    )


@router.get("/admin/cc-pair/{cc_pair_id}")
def get_cc_pair_full_info(
    cc_pair_id: int,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CCPairFullInfo:
    tenant_id = get_current_tenant_id()

    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, get_editable=False
    )
    if not cc_pair:
        raise HTTPException(
            status_code=404, detail="CC Pair not found for current user permissions"
        )
    editable_cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, get_editable=True
    )
    is_editable_for_current_user = editable_cc_pair is not None

    cc_pair_identifier = ConnectorCredentialPairIdentifier(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
    )

    document_count_info_list = list(
        get_document_counts_for_cc_pairs(
            db_session=db_session,
            cc_pair_identifiers=[cc_pair_identifier],
        )
    )
    documents_indexed = (
        document_count_info_list[0][-1] if document_count_info_list else 0
    )

    latest_attempt = get_latest_index_attempt_for_cc_pair_id(
        db_session=db_session,
        connector_credential_pair_id=cc_pair_id,
        secondary_index=False,
        only_finished=False,
    )

    search_settings = get_current_search_settings(db_session)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings.id)

    return CCPairFullInfo.from_models(
        cc_pair_model=cc_pair,
        number_of_index_attempts=count_index_attempts_for_connector(
            db_session=db_session,
            connector_id=cc_pair.connector_id,
        ),
        last_index_attempt=latest_attempt,
        latest_deletion_attempt=get_deletion_attempt_snapshot(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            db_session=db_session,
            tenant_id=tenant_id,
        ),
        num_docs_indexed=documents_indexed,
        is_editable_for_current_user=is_editable_for_current_user,
        indexing=redis_connector_index.fenced,
    )


@router.put("/admin/cc-pair/{cc_pair_id}/status")
def update_cc_pair_status(
    cc_pair_id: int,
    status_update_request: CCStatusUpdateRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> JSONResponse:
    """This method returns nearly immediately. It simply sets some signals and
    optimistically assumes any running background processes will clean themselves up.
    This is done to improve the perceived end user experience.

    Returns HTTPStatus.OK if everything finished.
    """
    tenant_id = get_current_tenant_id()

    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=True,
    )

    if not cc_pair:
        raise HTTPException(
            status_code=400,
            detail="Connection not found for current user's permissions",
        )

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if status_update_request.status == ConnectorCredentialPairStatus.PAUSED:
        redis_connector.stop.set_fence(True)

        search_settings_list: list[SearchSettings] = get_active_search_settings_list(
            db_session
        )

        while True:
            for search_settings in search_settings_list:
                redis_connector_index = redis_connector.new_index(search_settings.id)
                if not redis_connector_index.fenced:
                    continue

                index_payload = redis_connector_index.payload
                if not index_payload:
                    continue

                if not index_payload.celery_task_id:
                    continue

                # Revoke the task to prevent it from running
                primary_app.control.revoke(index_payload.celery_task_id)

                # If it is running, then signaling for termination will get the
                # watchdog thread to kill the spawned task
                redis_connector_index.set_terminate(index_payload.celery_task_id)

            break
    else:
        redis_connector.stop.set_fence(False)

    update_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        status=status_update_request.status,
    )

    db_session.commit()

    # this speeds up the start of indexing by firing the check immediately
    primary_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        kwargs=dict(tenant_id=tenant_id),
        priority=OnyxCeleryPriority.HIGH,
    )

    return JSONResponse(
        status_code=HTTPStatus.OK, content={"message": str(HTTPStatus.OK)}
    )


@router.put("/admin/cc-pair/{cc_pair_id}/name")
def update_cc_pair_name(
    cc_pair_id: int,
    new_name: str,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=True,
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400, detail="CC Pair not found for current user's permissions"
        )

    try:
        cc_pair.name = new_name
        db_session.commit()
        return StatusResponse(
            success=True, message="Name updated successfully", data=cc_pair_id
        )
    except IntegrityError:
        db_session.rollback()
        raise HTTPException(status_code=400, detail="Name must be unique")


@router.put("/admin/cc-pair/{cc_pair_id}/property")
def update_cc_pair_property(
    cc_pair_id: int,
    update_request: CCPropertyUpdateRequest,  # in seconds
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        get_editable=True,
    )
    if not cc_pair:
        raise HTTPException(
            status_code=400, detail="CC Pair not found for current user's permissions"
        )

    # Can we centralize logic for updating connector properties
    # so that we don't need to manually validate everywhere?
    if update_request.name == "refresh_frequency":
        cc_pair.connector.refresh_freq = int(update_request.value)
        cc_pair.connector.validate_refresh_freq()
        db_session.commit()

        msg = "Refresh frequency updated successfully"
    elif update_request.name == "pruning_frequency":
        cc_pair.connector.prune_freq = int(update_request.value)
        cc_pair.connector.validate_prune_freq()
        db_session.commit()

        msg = "Pruning frequency updated successfully"
    else:
        raise HTTPException(
            status_code=400, detail=f"Property name {update_request.name} is not valid."
        )

    return StatusResponse(success=True, message=msg, data=cc_pair_id)


@router.get("/admin/cc-pair/{cc_pair_id}/last_pruned")
def get_cc_pair_last_pruned(
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

    return cc_pair.last_pruned


@router.post("/admin/cc-pair/{cc_pair_id}/prune")
def prune_cc_pair(
    cc_pair_id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[list[int]]:
    """Triggers pruning on a particular cc_pair immediately"""
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
    if redis_connector.prune.fenced:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Pruning task already in progress.",
        )

    logger.info(
        f"Pruning cc_pair: cc_pair={cc_pair_id} "
        f"connector={cc_pair.connector_id} "
        f"credential={cc_pair.credential_id} "
        f"{cc_pair.connector.name} connector."
    )
    payload_id = try_creating_prune_generator_task(
        primary_app, cc_pair, db_session, r, tenant_id
    )
    if not payload_id:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Pruning task creation failed.",
        )

    logger.info(f"Pruning queued: cc_pair={cc_pair.id} id={payload_id}")

    return StatusResponse(
        success=True,
        message="Successfully created the pruning task.",
    )


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
) -> StatusResponse[list[int]]:
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
        primary_app, cc_pair_id, r, tenant_id
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
) -> StatusResponse[list[int]]:
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
        primary_app, cc_pair_id, r, tenant_id
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


@router.get("/admin/cc-pair/{cc_pair_id}/get-docs-sync-status")
def get_docs_sync_status(
    cc_pair_id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[DocumentSyncStatus]:
    all_docs_for_cc_pair = get_documents_for_cc_pair(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    return [DocumentSyncStatus.from_model(doc) for doc in all_docs_for_cc_pair]


@router.get("/admin/cc-pair/{cc_pair_id}/errors")
def get_cc_pair_indexing_errors(
    cc_pair_id: int,
    include_resolved: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[IndexAttemptErrorPydantic]:
    """Gives back all errors for a given CC Pair. Allows pagination based on page and page_size params.

    Args:
        cc_pair_id: ID of the connector-credential pair to get errors for
        include_resolved: Whether to include resolved errors in the results
        page: Page number for pagination, starting at 0
        page_size: Number of errors to return per page
        _: Current user, must be curator or admin
        db_session: Database session

    Returns:
        Paginated list of indexing errors for the CC pair.
    """
    total_count = count_index_attempt_errors_for_cc_pair(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        unresolved_only=not include_resolved,
    )

    index_attempt_errors = get_index_attempt_errors_for_cc_pair(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        unresolved_only=not include_resolved,
        page=page,
        page_size=page_size,
    )
    return PaginatedReturn(
        items=[IndexAttemptErrorPydantic.from_model(e) for e in index_attempt_errors],
        total_items=total_count,
    )


@router.put("/connector/{connector_id}/credential/{credential_id}")
def associate_credential_to_connector(
    connector_id: int,
    credential_id: int,
    metadata: ConnectorCredentialPairMetadata,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> StatusResponse[int]:
    """NOTE(rkuo): internally discussed and the consensus is this endpoint
    and create_connector_with_mock_credential should be combined.

    The intent of this endpoint is to handle connectors that actually need credentials.
    """

    fetch_ee_implementation_or_noop(
        "onyx.db.user_group", "validate_object_creation_for_user", None
    )(
        db_session=db_session,
        user=user,
        target_group_ids=metadata.groups,
        object_is_public=metadata.access_type == AccessType.PUBLIC,
        object_is_perm_sync=metadata.access_type == AccessType.SYNC,
    )

    try:
        response = add_credential_to_connector(
            db_session=db_session,
            user=user,
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_name=metadata.name,
            access_type=metadata.access_type,
            auto_sync_options=metadata.auto_sync_options,
            groups=metadata.groups,
        )

        # trigger indexing immediately
        primary_app.send_task(
            OnyxCeleryTask.CHECK_FOR_INDEXING,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
        )

        logger.info(
            f"associate_credential_to_connector - running check_for_indexing: "
            f"cc_pair={response.data}"
        )

        return response
    except IntegrityError as e:
        logger.error(f"IntegrityError: {e}")
        raise HTTPException(status_code=400, detail="Name must be unique")


@router.delete("/connector/{connector_id}/credential/{credential_id}")
def dissociate_credential_from_connector(
    connector_id: int,
    credential_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    return remove_credential_from_connector(
        connector_id, credential_id, user, db_session
    )
