from datetime import datetime
from http import HTTPStatus

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.background.celery.tasks.pruning.tasks import (
    try_creating_prune_generator_task,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.background.indexing.models import IndexAttemptErrorPydantic
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.exceptions import ValidationError
from onyx.connectors.factory import validate_ccpair_for_user
from onyx.db.connector import delete_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id_for_user,
)
from onyx.db.connector_credential_pair import remove_credential_from_connector
from onyx.db.connector_credential_pair import (
    update_connector_credential_pair_from_id,
)
from onyx.db.connector_credential_pair import verify_user_has_access_to_cc_pair
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.document import get_documents_for_cc_pair
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import PermissionSyncStatus
from onyx.db.index_attempt import count_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import count_index_attempts_for_cc_pair
from onyx.db.index_attempt import get_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.db.index_attempt import get_paginated_index_attempts_for_cc_pair_id
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import IndexAttempt
from onyx.db.models import User
from onyx.db.permission_sync_attempt import (
    get_latest_doc_permission_sync_attempt_for_cc_pair,
)
from onyx.db.permission_sync_attempt import (
    get_recent_doc_permission_sync_attempts_for_cc_pair,
)
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_utils import get_deletion_attempt_snapshot
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CCPairFullInfo
from onyx.server.documents.models import CCPropertyUpdateRequest
from onyx.server.documents.models import CCStatusUpdateRequest
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.server.documents.models import ConnectorCredentialPairMetadata
from onyx.server.documents.models import DocumentSyncStatus
from onyx.server.documents.models import IndexAttemptSnapshot
from onyx.server.documents.models import PaginatedReturn
from onyx.server.documents.models import PermissionSyncAttemptSnapshot
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
    if user:
        user_has_access = verify_user_has_access_to_cc_pair(
            cc_pair_id, db_session, user, get_editable=False
        )
        if not user_has_access:
            raise HTTPException(
                status_code=400, detail="CC Pair not found for current user permissions"
            )

    total_count = count_index_attempts_for_cc_pair(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    index_attempts = get_paginated_index_attempts_for_cc_pair_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
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


@router.get("/admin/cc-pair/{cc_pair_id}/permission-sync-attempts")
def get_cc_pair_permission_sync_attempts(
    cc_pair_id: int,
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=1000),
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[PermissionSyncAttemptSnapshot]:
    if user:
        user_has_access = verify_user_has_access_to_cc_pair(
            cc_pair_id, db_session, user, get_editable=False
        )
        if not user_has_access:
            raise HTTPException(
                status_code=400, detail="CC Pair not found for current user permissions"
            )

    # Get all permission sync attempts for this cc pair
    all_attempts = get_recent_doc_permission_sync_attempts_for_cc_pair(
        cc_pair_id=cc_pair_id,
        limit=1000,
        db_session=db_session,
    )

    start_idx = page_num * page_size
    end_idx = start_idx + page_size
    paginated_attempts = all_attempts[start_idx:end_idx]
    items = [
        PermissionSyncAttemptSnapshot.from_permission_sync_attempt_db_model(attempt)
        for attempt in paginated_attempts
    ]

    return PaginatedReturn(
        items=items,
        total_items=len(all_attempts),
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

    document_count_info_list = list(
        get_document_counts_for_cc_pairs(
            db_session=db_session,
            cc_pairs=[
                ConnectorCredentialPairIdentifier(
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                )
            ],
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

    # Get latest permission sync attempt for status
    latest_permission_sync_attempt = None
    if cc_pair.access_type == AccessType.SYNC:
        latest_permission_sync_attempt = (
            get_latest_doc_permission_sync_attempt_for_cc_pair(
                db_session=db_session,
                connector_credential_pair_id=cc_pair_id,
            )
        )

    return CCPairFullInfo.from_models(
        cc_pair_model=cc_pair,
        number_of_index_attempts=count_index_attempts_for_cc_pair(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
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
        indexing=bool(
            latest_attempt and latest_attempt.status == IndexingStatus.IN_PROGRESS
        ),
        last_permission_sync_attempt_status=(
            latest_permission_sync_attempt.status
            if latest_permission_sync_attempt
            else None
        ),
        permission_syncing=bool(
            latest_permission_sync_attempt
            and latest_permission_sync_attempt.status
            == PermissionSyncStatus.IN_PROGRESS
        ),
        last_permission_sync_attempt_finished=(
            latest_permission_sync_attempt.time_finished
            if latest_permission_sync_attempt
            else None
        ),
        last_permission_sync_attempt_error_message=(
            latest_permission_sync_attempt.error_message
            if latest_permission_sync_attempt
            else None
        ),
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

        # Request cancellation for any active indexing attempts for this cc_pair
        active_attempts = (
            db_session.execute(
                select(IndexAttempt).where(
                    IndexAttempt.connector_credential_pair_id == cc_pair_id,
                    IndexAttempt.status.in_(
                        [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                    ),
                )
            )
            .scalars()
            .all()
        )

        for attempt in active_attempts:
            try:
                IndexingCoordination.request_cancellation(db_session, attempt.id)
                # Revoke the task to prevent it from running
                if attempt.celery_task_id:
                    client_app.control.revoke(attempt.celery_task_id)
                logger.info(
                    f"Requested cancellation for active indexing attempt {attempt.id} "
                    f"due to connector pause: cc_pair={cc_pair_id}"
                )
            except Exception:
                logger.exception(
                    f"Failed to request cancellation for indexing attempt {attempt.id}"
                )

    else:
        redis_connector.stop.set_fence(False)

    update_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        status=status_update_request.status,
    )

    db_session.commit()

    # this speeds up the start of indexing by firing the check immediately
    client_app.send_task(
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
        client_app, cc_pair, db_session, r, tenant_id
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
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[IndexAttemptErrorPydantic]:
    """Gives back all errors for a given CC Pair. Allows pagination based on page and page_size params.

    Args:
        cc_pair_id: ID of the connector-credential pair to get errors for
        include_resolved: Whether to include resolved errors in the results
        page_num: Page number for pagination, starting at 0
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
        page=page_num,
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
        object_is_new=True,
    )

    try:
        validate_ccpair_for_user(
            connector_id, credential_id, metadata.access_type, db_session
        )

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
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_INDEXING,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
        )

        logger.info(
            f"associate_credential_to_connector - running check_for_indexing: "
            f"cc_pair={response.data}"
        )

        return response
    except ValidationError as e:
        # If validation fails, delete the connector and commit the changes
        # Ensures we don't leave invalid connectors in the database
        # NOTE: consensus is that it makes sense to unify connector and ccpair creation flows
        # which would rid us of needing to handle cases like these
        delete_connector(db_session, connector_id)
        db_session.commit()

        raise HTTPException(
            status_code=400, detail="Connector validation error: " + str(e)
        )
    except IntegrityError as e:
        logger.error(f"IntegrityError: {e}")
        delete_connector(db_session, connector_id)
        db_session.commit()

        raise HTTPException(status_code=400, detail="Name must be unique")

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")

        raise HTTPException(status_code=500, detail="Unexpected error")


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
