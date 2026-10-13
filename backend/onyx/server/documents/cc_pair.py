from datetime import datetime
from http import HTTPStatus

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.background.celery.tasks.pruning.tasks import try_creating_prune_generator_task
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.background.indexing.models import IndexAttemptErrorPydantic
from onyx.configs.constants import (
    PUBLIC_API_TAGS,
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryTask,
)
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.applicability import get_applicable_capabilities
from onyx.connectors.capability_checks.indexing_hold import get_first_indexing_hold
from onyx.connectors.capability_checks.indexing_hold_models import IndexingHold
from onyx.connectors.exceptions import ValidationError
from onyx.connectors.factory import identify_connector_class, validate_ccpair_for_user
from onyx.connectors.interfaces import Resolver
from onyx.connectors.models import InputType
from onyx.connectors.pairing_access import validate_pairing_access
from onyx.db.cc_pair_runs import (
    count_cc_pair_runs_by_status_group,
    get_cc_pair_run_page,
)
from onyx.db.cc_pair_runs_models import CCPairRunFilter, CCPairRunPage
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    add_credential_to_connector,
    get_cc_pair_groups_for_ids,
    get_cc_pair_ids_for_connector,
    get_connector_credential_pair,
    get_connector_credential_pair_for_user,
    get_connector_credential_pair_from_id_for_user,
    remove_credential_from_connector,
    update_connector_credential_pair_from_id,
    verify_user_can_manage_all_cc_pairs,
    verify_user_has_access_to_cc_pair,
)
from onyx.db.credentials import fetch_credential_by_id_for_user
from onyx.db.document import get_document_counts_for_cc_pairs, get_documents_for_cc_pair
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    AccessType,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    ConnectorManageRole,
    IndexingStatus,
    Permission,
    PermissionSyncStatus,
)
from onyx.db.index_attempt import (
    cancel_queued_index_attempt__no_commit,
    count_index_attempt_errors_for_cc_pair,
    count_index_attempts_for_cc_pair,
    get_error_counts_for_index_attempts,
    get_index_attempt,
    get_index_attempt_errors_for_cc_pair,
    get_latest_index_attempt_for_cc_pair_id,
    get_latest_successful_index_attempt_for_cc_pair_id,
    get_paginated_index_attempts_for_cc_pair_id,
    get_waiting_index_attempt,
)
from onyx.db.index_attempt_metrics import get_stage_metrics_for_attempt
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    User,
)
from onyx.db.permission_sync_attempt import (
    get_latest_doc_permission_sync_attempt_for_cc_pair,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_utils import get_deletion_attempt_snapshot
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.documents.credential import credential_ids_to_mask
from onyx.server.documents.hierarchy_breakdown import build_cc_pair_hierarchy_breakdown
from onyx.server.documents.models import (
    CCPairDocPermissionSyncRun,
    CCPairFullInfo,
    CCPairGroupSyncRun,
    CCPairHierarchyBreakdown,
    CCPairIndexRun,
    CCPairRun,
    CCPairRunsResponse,
    CCPropertyUpdateRequest,
    CCStatusUpdateRequest,
    ConnectorCredentialPairIdentifier,
    ConnectorCredentialPairMetadata,
    DocPermissionSyncAttemptSnapshot,
    DocumentSyncStatus,
    ExternalGroupSyncAttemptSnapshot,
    IndexAttemptSnapshot,
    IndexAttemptStageMetricSnapshot,
    IndexAttemptStageMetricsResponse,
    PaginatedReturn,
    synthesize_unaccounted,
)
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


def _get_readable_cc_pair(
    cc_pair_id: int, db_session: Session, user: User
) -> ConnectorCredentialPair | None:
    """Fetch a cc-pair for the detail page and its sub-resources.

    Neither filter contains the other, so both run: the read one drops a creator's
    groupless private pair and pairs managed only through a role, the operate one
    drops plain group membership. Operate runs second, so the common case still
    costs one query.
    """
    return get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, CCPairAccessLevel.READ
    ) or get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, CCPairAccessLevel.OPERATE
    )


def _get_readable_cc_pair_or_raise(
    cc_pair_id: int, db_session: Session, user: User
) -> ConnectorCredentialPair:
    """Same as _get_readable_cc_pair, but 403s when the caller cannot read the pair."""
    cc_pair = _get_readable_cc_pair(cc_pair_id, db_session, user)
    if cc_pair is None:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user permissions",
        )
    return cc_pair


@router.get("/admin/cc-pair/{cc_pair_id}/index-attempts", tags=PUBLIC_API_TAGS)
def get_cc_pair_index_attempts(
    cc_pair_id: int,
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=1000),
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[IndexAttemptSnapshot]:
    _get_readable_cc_pair_or_raise(cc_pair_id, db_session, user)

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
    error_counts = get_error_counts_for_index_attempts(
        db_session=db_session,
        index_attempt_ids=[index_attempt.id for index_attempt in index_attempts],
    )
    return PaginatedReturn(
        items=[
            IndexAttemptSnapshot.from_index_attempt_db_model(
                index_attempt,
                error_count=error_counts.get(index_attempt.id, 0),
            )
            for index_attempt in index_attempts
        ],
        total_items=total_count,
    )


@router.get("/admin/index-attempt/{index_attempt_id}/stage-metrics")
def get_index_attempt_stage_metrics(
    index_attempt_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> IndexAttemptStageMetricsResponse:
    """Return the per-stage timing breakdown for a single ``IndexAttempt``.

    Returned in pipeline (enum declaration) order. The frontend renders this
    order verbatim for the default "Pipeline order" sort and re-sorts
    client-side for the "Time taken" sort. Auth: caller must have at least
    read access to the cc-pair that owns the attempt.
    """
    index_attempt = get_index_attempt(
        db_session=db_session,
        index_attempt_id=index_attempt_id,
    )
    if index_attempt is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Index attempt not found")

    if (
        _get_readable_cc_pair(
            index_attempt.connector_credential_pair_id, db_session, user
        )
        is None
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You do not have access to this index attempt",
        )

    metrics = get_stage_metrics_for_attempt(
        db_session=db_session,
        index_attempt_id=index_attempt_id,
    )
    stages = [IndexAttemptStageMetricSnapshot.from_db_model(m) for m in metrics]
    # Append the BATCH_UNACCOUNTED residual (frontend re-sorts, so order is fine).
    unaccounted = synthesize_unaccounted(stages)
    if unaccounted is not None:
        stages.append(unaccounted)
    return IndexAttemptStageMetricsResponse(
        index_attempt_id=index_attempt_id,
        stages=stages,
    )


_RUNS_MAX_PAGE_SIZE = 50


def _cc_pair_run_kinds(cc_pair: ConnectorCredentialPair) -> list[CCPairRunKind]:
    """Indexing always, plus the permission syncs a perm-synced pair's source runs."""
    kinds = [CCPairRunKind.INDEXING]
    if not cc_pair.access_type.is_perm_synced():
        return kinds
    capabilities = get_applicable_capabilities(cc_pair.connector.source)
    if CredentialCapability.DOC_PERMISSION_SYNC in capabilities:
        kinds.append(CCPairRunKind.DOC_PERMISSION_SYNC)
    if CredentialCapability.EXTERNAL_GROUP_SYNC in capabilities:
        kinds.append(CCPairRunKind.GROUP_SYNC)
    return kinds


def _run_item(
    kind: CCPairRunKind, run_id: int, page: CCPairRunPage, error_counts: dict[int, int]
) -> CCPairRun:
    match kind:
        case CCPairRunKind.INDEXING:
            attempt = page.index_attempts[run_id]
            return CCPairIndexRun(
                time_created=attempt.time_created,
                attempt=IndexAttemptSnapshot.from_index_attempt_db_model(
                    attempt, error_count=error_counts.get(run_id, 0)
                ),
            )
        case CCPairRunKind.DOC_PERMISSION_SYNC:
            sync = page.doc_permission_syncs[run_id]
            return CCPairDocPermissionSyncRun(
                time_created=sync.time_created,
                attempt=DocPermissionSyncAttemptSnapshot.from_doc_permission_sync_attempt_db_model(
                    sync
                ),
            )
        case CCPairRunKind.GROUP_SYNC:
            group_sync = page.group_syncs[run_id]
            return CCPairGroupSyncRun(
                time_created=group_sync.time_created,
                attempt=ExternalGroupSyncAttemptSnapshot.from_external_group_sync_attempt_db_model(
                    group_sync
                ),
            )


@router.get("/admin/cc-pair/{cc_pair_id}/runs")
def get_cc_pair_runs(
    cc_pair_id: int,
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=_RUNS_MAX_PAGE_SIZE),
    since: datetime | None = Query(None),
    kinds: list[CCPairRunKind] | None = Query(None),
    status_groups: list[CCPairRunStatusGroup] | None = Query(None),
    q: str | None = Query(None, max_length=200),
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CCPairRunsResponse:
    """The pair's index attempts and permission syncs as one feed, newest
    first. ``since`` windows on creation time and ``q`` matches error messages."""
    cc_pair = _get_readable_cc_pair_or_raise(cc_pair_id, db_session, user)
    pair_kinds = _cc_pair_run_kinds(cc_pair)
    wanted = [kind for kind in pair_kinds if kinds is None or kind in kinds]
    groups = None if status_groups is None else set(status_groups)
    run_filter = CCPairRunFilter(
        cc_pair_id=cc_pair_id,
        source=cc_pair.connector.source,
        since=since,
        error_query=(q or "").strip() or None,
        status_groups=groups,
    )
    page = get_cc_pair_run_page(
        db_session,
        wanted,
        run_filter,
        offset=page_num * page_size,
        limit=page_size,
    )
    error_counts = get_error_counts_for_index_attempts(
        db_session, list(page.index_attempts)
    )
    status_counts = count_cc_pair_runs_by_status_group(db_session, wanted, run_filter)
    return CCPairRunsResponse(
        items=[
            _run_item(kind, run_id, page, error_counts) for kind, run_id in page.order
        ],
        total_items=sum(
            count
            for group, count in status_counts.items()
            if groups is None or group in groups
        ),
        kinds=pair_kinds,
        status_counts=status_counts,
    )


def _cancel_index_attempt(
    db_session: Session, attempt: IndexAttempt, reason: str
) -> None:
    """Cancels an active attempt and commits. A queued one ends in the database
    before its task is revoked, so a revoked task never leaves it queued. A
    running one gets a request, which its task reads."""
    if cancel_queued_index_attempt__no_commit(db_session, attempt.id, reason):
        db_session.commit()
    else:
        IndexingCoordination.request_cancellation(db_session, attempt.id)
    if attempt.celery_task_id:
        client_app.control.revoke(attempt.celery_task_id)


@router.post("/admin/index-attempt/{index_attempt_id}/cancel")
def cancel_index_attempt(
    index_attempt_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    """Cancels one running or queued index attempt of a pair the caller operates."""
    attempt = get_index_attempt(db_session, index_attempt_id)
    if attempt is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Index attempt not found")
    if not verify_user_has_access_to_cc_pair(
        attempt.connector_credential_pair_id,
        db_session,
        user,
        CCPairAccessLevel.OPERATE,
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You do not have access to this index attempt",
        )
    if attempt.status.is_terminal():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Index attempt is not running.")

    _cancel_index_attempt(db_session, attempt, reason="Canceled by a user.")
    db_session.commit()
    emit_audit_event(
        AuditAction.CC_PAIR_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="cc_pair",
        resource_id=attempt.connector_credential_pair_id,
        extra={"canceled_index_attempt_id": index_attempt_id},
    )


def _get_indexing_hold(
    db_session: Session, cc_pair: ConnectorCredentialPair, *, can_operate: bool
) -> IndexingHold | None:
    """The hold on the pair's first index attempt, with the attempt that waits
    when it is created. The failed checks are report internals, which are
    management data, so a viewer who cannot operate the pair gets only the
    reason."""
    hold = get_first_indexing_hold(db_session, cc_pair)
    if hold is None:
        return None
    waiting = get_waiting_index_attempt(
        db_session, cc_pair.id, get_current_search_settings(db_session).id
    )
    return IndexingHold(
        reason=hold.reason,
        failed_checks=hold.failed_checks if can_operate else [],
        index_attempt_id=waiting.id if waiting is not None else None,
    )


@router.get("/admin/cc-pair/{cc_pair_id}", tags=PUBLIC_API_TAGS)
def get_cc_pair_full_info(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CCPairFullInfo:
    tenant_id = get_current_tenant_id()

    # this route needs both halves of _get_readable_cc_pair, so it fetches them directly
    operable_cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, CCPairAccessLevel.OPERATE
    )
    cc_pair = (
        get_connector_credential_pair_from_id_for_user(
            cc_pair_id, db_session, user, CCPairAccessLevel.READ
        )
        or operable_cc_pair
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "CC Pair not found for current user permissions",
        )
    can_operate = operable_cc_pair is not None
    can_edit = can_operate and verify_user_has_access_to_cc_pair(
        cc_pair_id, db_session, user, CCPairAccessLevel.EDIT
    )

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

    latest_successful_attempt = get_latest_successful_index_attempt_for_cc_pair_id(
        db_session=db_session,
        connector_credential_pair_id=cc_pair_id,
    )

    # Get latest permission sync attempt for status
    latest_permission_sync_attempt = None
    if cc_pair.access_type.is_perm_synced():
        latest_permission_sync_attempt = (
            get_latest_doc_permission_sync_attempt_for_cc_pair(
                db_session=db_session,
                connector_credential_pair_id=cc_pair_id,
            )
        )

    return CCPairFullInfo.from_models(
        cc_pair_model=cc_pair,
        mask_credential_prefix=bool(
            credential_ids_to_mask([cc_pair.credential], user, db_session)
        ),
        is_connectors_admin=has_global_permission(user, Permission.MANAGE_CONNECTORS),
        can_edit=can_edit,
        groups=[
            relationship.user_group_id
            for relationship in get_cc_pair_groups_for_ids(db_session, [cc_pair_id])
            # A group update tombstones the old row until the sync clears it, so
            # an unfiltered read reports groups the pair has already left.
            if relationship.is_current
        ],
        number_of_index_attempts=count_index_attempts_for_cc_pair(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
        ),
        last_index_attempt=latest_attempt,
        last_successful_index_time=(
            latest_successful_attempt.time_started
            if latest_successful_attempt
            else None
        ),
        latest_deletion_attempt=get_deletion_attempt_snapshot(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            db_session=db_session,
            tenant_id=tenant_id,
        ),
        num_docs_indexed=documents_indexed,
        is_editable_for_current_user=can_operate,
        indexing_hold=_get_indexing_hold(db_session, cc_pair, can_operate=can_operate),
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
        supports_targeted_reindex=_connector_supports_targeted_reindex(
            cc_pair.connector.source, cc_pair.connector.input_type
        ),
    )


@router.get("/admin/cc-pair/{cc_pair_id}/hierarchy-breakdown")
def get_cc_pair_hierarchy_breakdown(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CCPairHierarchyBreakdown | None:
    """Document counts per hierarchy node (e.g. Confluence spaces). None until
    the pair has a successful index attempt. A separate route, because the count
    reads every document of the pair and the detail page must load fast."""
    cc_pair = _get_readable_cc_pair_or_raise(cc_pair_id, db_session, user)
    return build_cc_pair_hierarchy_breakdown(db_session, cc_pair)


def _connector_supports_targeted_reindex(
    source: DocumentSource, input_type: InputType
) -> bool:
    try:
        return issubclass(identify_connector_class(source, input_type), Resolver)
    except Exception:
        return False


@router.put("/admin/cc-pair/{cc_pair_id}/status", tags=PUBLIC_API_TAGS)
def update_cc_pair_status(
    cc_pair_id: int,
    status_update_request: CCStatusUpdateRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
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
        access_level=CCPairAccessLevel.OPERATE,
    )

    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    # Pause/resume only. Accepting DELETING here would let an Operator delete via the
    # operate gate, bypassing the Editor-only /deletion-attempt route.
    if status_update_request.status not in (
        ConnectorCredentialPairStatus.ACTIVE,
        ConnectorCredentialPairStatus.PAUSED,
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Connector status can only be set to ACTIVE or PAUSED.",
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
                # The status commit below also commits a waiting attempt's cancel.
                _cancel_index_attempt(db_session, attempt, reason="Connector paused.")
                logger.info(
                    "Requested cancellation for active indexing attempt %s due to connector pause: cc_pair=%s",
                    attempt.id,
                    cc_pair_id,
                )
            except Exception:
                logger.exception(
                    "Failed to request cancellation for indexing attempt %s", attempt.id
                )

    else:
        redis_connector.stop.set_fence(False)

    update_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
        status=status_update_request.status,
    )

    db_session.commit()

    emit_audit_event(
        AuditAction.CC_PAIR_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="cc_pair",
        resource_id=cc_pair_id,
        extra={"status": status_update_request.status.value},
    )

    # this speeds up the start of indexing by firing the check immediately
    client_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        kwargs={"tenant_id": tenant_id},
        priority=OnyxCeleryPriority.HIGH,
    )

    return JSONResponse(
        status_code=HTTPStatus.OK, content={"message": str(HTTPStatus.OK)}
    )


@router.put("/admin/cc-pair/{cc_pair_id}/name")
def update_cc_pair_name(
    cc_pair_id: int,
    new_name: str,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.OPERATE,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user's permissions",
        )

    try:
        cc_pair.name = new_name
        db_session.commit()
        return StatusResponse(
            success=True, message="Name updated successfully", data=cc_pair_id
        )
    except IntegrityError:
        db_session.rollback()
        raise OnyxError(
            OnyxErrorCode.CONFLICT, f"Could not rename cc-pair {cc_pair_id}."
        )


@router.put("/admin/cc-pair/{cc_pair_id}/property")
def update_cc_pair_property(
    cc_pair_id: int,
    update_request: CCPropertyUpdateRequest,  # in seconds
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
        user=user,
        access_level=CCPairAccessLevel.OPERATE,
    )
    if not cc_pair:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "CC Pair not found for current user's permissions",
        )

    # GATE 2 on every pair on this connector: refresh_freq and prune_freq live on the
    # shared Connector row. No empty guard — empty is the right side to fail on here
    if not verify_user_can_manage_all_cc_pairs(
        get_cc_pair_ids_for_connector(db_session, cc_pair.connector_id),
        db_session,
        user,
        CCPairAccessLevel.OPERATE,
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This setting is shared across all connections on this connector.",
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
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Property name {update_request.name} is not valid.",
        )

    return StatusResponse(success=True, message=msg, data=cc_pair_id)


@router.get("/admin/cc-pair/{cc_pair_id}/last_pruned")
def get_cc_pair_last_pruned(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> datetime | None:
    cc_pair = _get_readable_cc_pair_or_raise(cc_pair_id, db_session, user)
    return cc_pair.last_pruned


@router.post("/admin/cc-pair/{cc_pair_id}/prune", tags=PUBLIC_API_TAGS)
def prune_cc_pair(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> StatusResponse[list[int]]:
    """Triggers pruning on a particular cc_pair immediately"""
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
    if redis_connector.prune.fenced:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Pruning task already in progress.",
        )

    logger.info(
        "Pruning cc_pair: cc_pair=%s connector=%s credential=%s %s connector.",
        cc_pair_id,
        cc_pair.connector_id,
        cc_pair.credential_id,
        cc_pair.connector.name,
    )
    payload_id = try_creating_prune_generator_task(
        client_app, cc_pair, db_session, r, tenant_id
    )
    if not payload_id:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Pruning task creation failed.",
        )

    logger.info("Pruning queued: cc_pair=%s id=%s", cc_pair.id, payload_id)

    return StatusResponse(
        success=True,
        message="Successfully created the pruning task.",
    )


@router.get("/admin/cc-pair/{cc_pair_id}/get-docs-sync-status")
def get_docs_sync_status(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[DocumentSyncStatus]:
    _get_readable_cc_pair_or_raise(cc_pair_id, db_session, user)

    all_docs_for_cc_pair = get_documents_for_cc_pair(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    return [DocumentSyncStatus.from_model(doc) for doc in all_docs_for_cc_pair]


@router.get("/admin/cc-pair/{cc_pair_id}/errors", tags=PUBLIC_API_TAGS)
def get_cc_pair_indexing_errors(
    cc_pair_id: int,
    include_resolved: bool = Query(False),
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[IndexAttemptErrorPydantic]:
    """Gives back all errors for a given CC Pair. Allows pagination based on page and page_size params.

    Args:
        cc_pair_id: ID of the connector-credential pair to get errors for
        include_resolved: Whether to include resolved errors in the results
        page_num: Page number for pagination, starting at 0
        page_size: Number of errors to return per page
        user: Current user; must be able to read this CC pair
        db_session: Database session

    Returns:
        Paginated list of indexing errors for the CC pair.
    """
    _get_readable_cc_pair_or_raise(cc_pair_id, db_session, user)

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


def authorize_pairing(
    metadata: ConnectorCredentialPairMetadata, user: User, db_session: Session
) -> dict[int, ConnectorManageRole]:
    """Runs the GATE 2 scope check for a new pair's manage groups, and returns
    them. Shared by every path that pairs a connector with a credential. The
    access-type rules are ``validate_pairing_access``."""

    # GATE 2 write authorization (see assert_within_scope).
    #
    # A permission-synced connector carrying no groups is exempt: its ACLs are
    # mirrored from the source, so it cannot surface a document to anyone who
    # could not already read it there. There is no reach for a group to bound,
    # and requiring one would attach a group that does not affect access at all.
    # Groups may still be supplied to scope who may *manage* it, and those are
    # checked normally below.
    manage_access = metadata.manage_roles_by_group()
    is_groupless_perm_sync = metadata.access_type.is_perm_synced() and not manage_access
    if not is_groupless_perm_sync:
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=[],
            requested_group_ids=manage_access.keys(),
            is_non_public=metadata.access_type != AccessType.PUBLIC,
        )
    return manage_access


@router.put(
    "/connector/{connector_id}/credential/{credential_id}", tags=PUBLIC_API_TAGS
)
def associate_credential_to_connector(
    connector_id: int,
    credential_id: int,
    metadata: ConnectorCredentialPairMetadata,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> StatusResponse[int]:
    """NOTE(rkuo): internally discussed and the consensus is this endpoint
    and create_connector_with_mock_credential should be combined.

    The intent of this endpoint is to handle connectors that actually need credentials.
    """

    manage_access = authorize_pairing(metadata, user, db_session)

    # GATE 2 on the connector: it carries no creator or groups, so its pairs are what
    # says who may edit it. Empty means nobody owns it yet (create-then-associate)
    existing_cc_pair_ids = get_cc_pair_ids_for_connector(db_session, connector_id)
    if existing_cc_pair_ids and not verify_user_can_manage_all_cc_pairs(
        existing_cc_pair_ids, db_session, user, CCPairAccessLevel.EDIT
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    # GATE 2 on the credential: validate_ccpair_for_user builds and probes the
    # connector, so ownership has to be settled before it runs.
    if fetch_credential_by_id_for_user(credential_id, user, db_session) is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    # After GATE 2: the access rules name the connector's source in their
    # errors, so only a user who may edit the connector reaches them.
    connector = fetch_connector_by_id(connector_id, db_session)
    if connector is None:
        raise OnyxError(
            OnyxErrorCode.CONNECTOR_NOT_FOUND,
            f"Connector {connector_id} does not exist",
        )
    validate_pairing_access(
        db_session,
        user=user,
        source=connector.source,
        access_type=metadata.access_type,
        data_access_group_ids=metadata.data_access,
    )

    # Validation claims the pairing's report row, so a duplicate request must
    # stop before it: it would replace the live pair's report and fence out its
    # run. The add below still answers a concurrent duplicate.
    if (
        get_connector_credential_pair(db_session, connector_id, credential_id)
        is not None
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"Connector {connector_id} is already associated with credential "
            f"{credential_id}.",
        )

    try:
        validate_ccpair_for_user(
            connector_id,
            credential_id,
            metadata.access_type,
            db_session,
            user=user,
        )

        response = add_credential_to_connector(
            db_session=db_session,
            user=user,
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_name=metadata.name,
            access_type=metadata.access_type,
            auto_sync_options=metadata.auto_sync_options,
            manage_access=manage_access,
            data_access_group_ids=metadata.data_access,
            processing_mode=metadata.processing_mode,
        )

        if not response.success:
            # The pair already exists. This used to answer 200 with success in
            # the body and the *connector* id in data, so a caller checking the
            # status stored the wrong id and reported a no-op as a success.
            raise OnyxError(OnyxErrorCode.CONFLICT, response.message)

        # Tenant-work-gating lifecycle hook: keep new-tenant latency to
        # seconds instead of one full-fanout interval.
        maybe_mark_tenant_active(tenant_id, caller="cc_pair_lifecycle")

        # trigger indexing immediately
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_INDEXING,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
        )

        logger.info(
            "associate_credential_to_connector - running check_for_indexing: cc_pair=%s",
            response.data,
        )

        emit_audit_event(
            AuditAction.CC_PAIR_CREATE,
            AuditOutcome.SUCCESS,
            actor=actor_from_user(user),
            resource_type="cc_pair",
            resource_id=response.data,
            extra={"connector_id": connector_id, "credential_id": credential_id},
        )
        return response
    except ValidationError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Connector validation error: " + str(e),
        )
    except IntegrityError:
        # The connector is a separately owned object the caller created before
        # this call, so a failed association rolls back rather than deleting it.
        # The unique name constraint this once reported was dropped in
        # 76b60d407dfb, so a collision here is on (connector_id, credential_id).
        logger.exception("IntegrityError associating credential to connector")
        db_session.rollback()

        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"Connector {connector_id} is already associated with credential "
            f"{credential_id}.",
        )

    except OnyxError:
        # Deliberate, already-classified failures must not be re-rendered as 500
        # by the catch-all below.
        raise
    except Exception as e:
        logger.exception("Unexpected error: %s", e)

        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Unexpected error")


@router.delete(
    "/connector/{connector_id}/credential/{credential_id}", tags=PUBLIC_API_TAGS
)
def dissociate_credential_from_connector(
    connector_id: int,
    credential_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    # Capture the cc_pair id before removal — remove_credential_from_connector
    # returns the connector_id (not the cc_pair id) in its StatusResponse.
    cc_pair = get_connector_credential_pair_for_user(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        user=user,
        access_level=CCPairAccessLevel.EDIT,
    )
    cc_pair_id = cc_pair.id if cc_pair else None

    result = remove_credential_from_connector(
        connector_id, credential_id, user, db_session
    )

    # Only emit when something was actually dissociated (a no-op returns
    # success=False without raising).
    if result.success:
        emit_audit_event(
            AuditAction.CC_PAIR_DELETE,
            AuditOutcome.SUCCESS,
            actor=actor_from_user(user),
            resource_type="cc_pair",
            resource_id=cc_pair_id,
            extra={"connector_id": connector_id, "credential_id": credential_id},
        )
    return result
