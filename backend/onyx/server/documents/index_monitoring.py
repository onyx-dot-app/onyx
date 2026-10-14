"""The indexing status page's fleet-wide reads: every pair the caller can read
as one population, where the pair routes in cc_pair.py read one pair."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from onyx.auth.permission_projection import cc_pair_permissions
from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.constants import DEFAULT_CC_PAIR_ID
from onyx.db.cc_pair_runs import count_pairs_indexing
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_connector_credential_pairs_for_user,
    get_managed_cc_pair_ids,
)
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus, IndexingStatus, Permission
from onyx.db.federated import fetch_all_federated_connectors
from onyx.db.index_attempt import (
    get_error_counts_for_index_attempts,
    get_latest_index_attempts,
    get_open_doc_error_counts_for_index_attempts,
    get_queued_index_attempts,
)
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, User
from onyx.server.documents.cc_pair_throughput import throughput_of
from onyx.server.documents.models import (
    CCPairThroughputWindow,
    ConnectorCredentialPairIdentifier,
    IndexAttemptSnapshot,
    IndexingConnectorRow,
    IndexingConnectorsResponse,
    IndexingConnectorStatus,
    IndexingOverviewResponse,
)
from onyx.server.federated.models import FederatedConnectorStatus

router = APIRouter(prefix="/manage/admin/index-monitoring")

_CONNECTORS_MAX_PAGE_SIZE = 100
_SEARCH_MAX_LENGTH = 200

# Rank per bucket, in enum order.
_STATUS_ORDER = {status: rank for rank, status in enumerate(IndexingConnectorStatus)}


def _readable_cc_pairs(
    db_session: Session, user: User
) -> dict[int, ConnectorCredentialPair]:
    """Every pair the caller can read, by id. Neither access level contains the
    other for a scoped manager, so both are read. An admin reads all at once."""
    levels = (
        [CCPairAccessLevel.READ]
        if has_global_permission(user, Permission.MANAGE_CONNECTORS)
        else [CCPairAccessLevel.READ, CCPairAccessLevel.OPERATE]
    )
    pairs: dict[int, ConnectorCredentialPair] = {}
    for level in levels:
        for cc_pair in get_connector_credential_pairs_for_user(
            db_session,
            user,
            level,
            eager_load_connector=True,
            eager_load_credential=True,
            eager_load_user=True,
            defer_connector_config=True,
            eager_load_creator=True,
        ):
            # The ingestion API's pair, which the status page never lists.
            if cc_pair.id == DEFAULT_CC_PAIR_ID:
                continue
            # A pair mid-deletion can have lost its connector or credential.
            if cc_pair.connector is None or cc_pair.credential is None:
                continue
            pairs[cc_pair.id] = cc_pair
    return pairs


def _managed_ids(
    db_session: Session,
    user: User,
    cc_pair_ids: set[int],
    level: CCPairAccessLevel,
    is_connectors_admin: bool,
) -> set[int]:
    """The pairs among ``cc_pair_ids`` the caller holds ``level`` on. An admin holds every level."""
    if is_connectors_admin:
        return cc_pair_ids
    return get_managed_cc_pair_ids(cc_pair_ids, db_session, user, level)


def _latest_index_attempts(db_session: Session) -> dict[int, IndexAttempt]:
    """Each pair's newest index attempt under the current search settings, by
    pair id. A backfill is the pair's current run while it goes, so it counts."""
    return {
        attempt.connector_credential_pair_id: attempt
        for attempt in get_latest_index_attempts(
            False, db_session, ignore_backfill=False
        )
    }


def _docs_indexed_by_pair(
    db_session: Session, pairs: dict[int, ConnectorCredentialPair]
) -> dict[int, int]:
    """Indexed documents per pair id, counted for these pairs only."""
    counts = {
        (connector_id, credential_id): count
        for connector_id, credential_id, count in get_document_counts_for_cc_pairs(
            db_session,
            [
                ConnectorCredentialPairIdentifier(
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                )
                for cc_pair in pairs.values()
            ],
        )
    }
    return {
        cc_pair_id: counts.get((cc_pair.connector_id, cc_pair.credential_id), 0)
        for cc_pair_id, cc_pair in pairs.items()
    }


@router.get("/overview")
def get_indexing_overview(
    window: CCPairThroughputWindow = Query(CCPairThroughputWindow.HOURS_1),
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> IndexingOverviewResponse:
    """The overview card's figures and throughput over the readable pairs."""
    pairs = _readable_cc_pairs(db_session, user)
    throughput = throughput_of(db_session, list(pairs), window)
    return IndexingOverviewResponse(
        indexing_connectors=count_pairs_indexing(db_session, list(pairs)),
        active_connectors=sum(
            1 for cc_pair in pairs.values() if cc_pair.status.is_active()
        ),
        recent_docs_indexed=sum(throughput.docs_indexed),
        total_docs_indexed=sum(_docs_indexed_by_pair(db_session, pairs).values()),
        throughput=throughput,
    )


def _connector_status(
    cc_pair: ConnectorCredentialPair, latest: IndexAttempt | None
) -> IndexingConnectorStatus:
    """The pair's bucket, as its status tag reads: the pair's own state first,
    then the latest attempt's. A live attempt outranks the sticky error."""
    if cc_pair.status == ConnectorCredentialPairStatus.PAUSED:
        return IndexingConnectorStatus.PAUSED
    if cc_pair.status in (
        ConnectorCredentialPairStatus.DELETING,
        ConnectorCredentialPairStatus.INVALID,
    ):
        return IndexingConnectorStatus.FAILED
    running = latest is not None and latest.status == IndexingStatus.IN_PROGRESS
    if cc_pair.in_repeated_error_state and not running:
        return IndexingConnectorStatus.FAILED
    if latest is None:
        return IndexingConnectorStatus.SCHEDULED
    match latest.status:
        case IndexingStatus.IN_PROGRESS:
            return IndexingConnectorStatus.INDEXING
        # A canceled or interrupted run never completed, and the pair runs again.
        case (
            IndexingStatus.NOT_STARTED
            | IndexingStatus.CANCELED
            | IndexingStatus.INTERRUPTED
        ):
            return IndexingConnectorStatus.SCHEDULED
        case IndexingStatus.FAILED:
            return IndexingConnectorStatus.FAILED
        case _:
            return IndexingConnectorStatus.INDEXED


def _queue_positions(db_session: Session) -> dict[int, int]:
    """Each pair's first queued attempt's place in line, from 1. Every attempt
    handed to the queue counts, other pairs' and other search settings' too,
    since they share it. The queue also serves a pair's first run ahead of
    repeats, so the place is where the attempt stands by age."""
    positions: dict[int, int] = {}
    for position, attempt in enumerate(get_queued_index_attempts(db_session), 1):
        positions.setdefault(attempt.connector_credential_pair_id, position)
    return positions


def _federated_rows(
    db_session: Session, query: str | None
) -> list[FederatedConnectorStatus]:
    rows = [
        FederatedConnectorStatus(
            id=federated.id,
            source=federated.source,
            name=federated.source.replace("_", " ").title(),
        )
        for federated in fetch_all_federated_connectors(db_session)
    ]
    if query is None:
        return rows
    return [row for row in rows if query in row.name.lower()]


@router.get("/connectors")
def get_indexing_connectors(
    page_num: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=_CONNECTORS_MAX_PAGE_SIZE),
    q: str | None = Query(None, max_length=_SEARCH_MAX_LENGTH),
    status: IndexingConnectorStatus | None = Query(None),
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> IndexingConnectorsResponse:
    """The readable pairs page, sorted by status then name. ``q`` matches the name."""
    pairs = _readable_cc_pairs(db_session, user)
    latest = _latest_index_attempts(db_session)
    query = (q or "").strip().lower() or None
    statuses = {
        cc_pair_id: _connector_status(cc_pair, latest.get(cc_pair_id))
        for cc_pair_id, cc_pair in pairs.items()
    }
    searched = [
        cc_pair
        for cc_pair in pairs.values()
        if query is None or query in cc_pair.name.lower()
    ]
    status_counts = dict.fromkeys(IndexingConnectorStatus, 0)
    for cc_pair in searched:
        status_counts[statuses[cc_pair.id]] += 1
    matching = sorted(
        (
            cc_pair
            for cc_pair in searched
            if status is None or statuses[cc_pair.id] == status
        ),
        # The id breaks name ties, so a page boundary splits same-named pairs the same way every request.
        key=lambda cc_pair: (
            _STATUS_ORDER[statuses[cc_pair.id]],
            cc_pair.name.lower(),
            cc_pair.id,
        ),
    )
    page = matching[page_num * page_size : (page_num + 1) * page_size]

    is_connectors_admin = has_global_permission(user, Permission.MANAGE_CONNECTORS)
    page_ids = {cc_pair.id for cc_pair in page}
    operate_ids = _managed_ids(
        db_session, user, page_ids, CCPairAccessLevel.OPERATE, is_connectors_admin
    )
    edit_ids = _managed_ids(
        db_session, user, page_ids, CCPairAccessLevel.EDIT, is_connectors_admin
    )
    attempt_ids = [latest[cc_pair.id].id for cc_pair in page if cc_pair.id in latest]
    error_counts = get_error_counts_for_index_attempts(db_session, attempt_ids)
    open_counts = get_open_doc_error_counts_for_index_attempts(db_session, attempt_ids)
    docs_indexed = _docs_indexed_by_pair(
        db_session, {cc_pair.id: cc_pair for cc_pair in page}
    )
    queue_positions = _queue_positions(db_session)

    def row(cc_pair: ConnectorCredentialPair) -> IndexingConnectorRow:
        attempt = latest.get(cc_pair.id)
        return IndexingConnectorRow(
            cc_pair_id=cc_pair.id,
            name=cc_pair.name,
            source=cc_pair.connector.source,
            access_type=cc_pair.access_type,
            cc_pair_status=cc_pair.status,
            status=statuses[cc_pair.id],
            creator_email=cc_pair.creator.email if cc_pair.creator else None,
            docs_indexed=docs_indexed[cc_pair.id],
            last_success=cc_pair.last_successful_index_time,
            latest_index_attempt=(
                None
                if attempt is None
                else IndexAttemptSnapshot.from_index_attempt_db_model(
                    attempt,
                    error_count=error_counts.get(attempt.id, 0),
                    open_doc_error_count=open_counts.get(attempt.id, 0),
                )
            ),
            queue_position=queue_positions.get(cc_pair.id),
            permissions=cc_pair_permissions(
                can_operate=cc_pair.id in operate_ids,
                can_edit=cc_pair.id in edit_ids,
                is_connectors_admin=is_connectors_admin,
            ),
        )

    return IndexingConnectorsResponse(
        items=[row(cc_pair) for cc_pair in page],
        total_items=len(matching),
        status_counts=status_counts,
        # A federated connector has no group to scope by, so only admins see it.
        federated_connectors=(
            _federated_rows(db_session, query)
            if is_connectors_admin and page_num == 0 and status is None
            else []
        ),
    )
