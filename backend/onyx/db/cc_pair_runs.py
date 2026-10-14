"""Queries behind a pair's run history. Each kind of run (index attempts,
document permission syncs, group syncs, prunes, connector checks) is windowed
and searched the same way, and one union pages every kind newest first, so no
page loads the runs before it."""

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    cast,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.cc_pair_runs_models import CCPairRunFilter, CCPairRunPage
from onyx.db.enums import (
    CapabilityCheckRunStatus,
    CCPairRunErrors,
    CCPairRunKind,
    CCPairRunStatusGroup,
    IndexingStatus,
    IndexModelStatus,
    PermissionSyncStatus,
    SyncStatus,
    SyncType,
)
from onyx.db.models import (
    CapabilityCheckRun,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
    SyncRecord,
)
from onyx.db.permission_sync_attempt import (
    relevant_external_group_sync_attempts_filter,
)

# Keyed by value, so a value two status enums share must group the same way.
# PermissionSyncStatus and SyncStatus values are all IndexingStatus values.
_STATUS_GROUPS: dict[str, CCPairRunStatusGroup] = {
    IndexingStatus.NOT_STARTED.value: CCPairRunStatusGroup.RUNNING,
    IndexingStatus.IN_PROGRESS.value: CCPairRunStatusGroup.RUNNING,
    IndexingStatus.SUCCESS.value: CCPairRunStatusGroup.SUCCEEDED,
    IndexingStatus.COMPLETED_WITH_ERRORS.value: CCPairRunStatusGroup.SUCCEEDED,
    IndexingStatus.FAILED.value: CCPairRunStatusGroup.FAILED,
    IndexingStatus.CANCELED.value: CCPairRunStatusGroup.CANCELED,
    IndexingStatus.INTERRUPTED.value: CCPairRunStatusGroup.CANCELED,
    CapabilityCheckRunStatus.RUNNING.value: CCPairRunStatusGroup.RUNNING,
    CapabilityCheckRunStatus.PASSED.value: CCPairRunStatusGroup.SUCCEEDED,
    CapabilityCheckRunStatus.FAILED_TO_RUN.value: CCPairRunStatusGroup.FAILED,
}

_StatusT = TypeVar(
    "_StatusT",
    IndexingStatus,
    PermissionSyncStatus,
    SyncStatus,
    CapabilityCheckRunStatus,
)
_RunT = TypeVar(
    "_RunT",
    IndexAttempt,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    SyncRecord,
    CapabilityCheckRun,
)


def _narrowed(
    stmt: Select,
    run_filter: CCPairRunFilter,
    time_created: InstrumentedAttribute[datetime],
    matches_error: Callable[[str], ColumnElement[bool]],
    status: InstrumentedAttribute[_StatusT],
    statuses: type[_StatusT],
    with_status_filter: bool,
) -> Select:
    if run_filter.since is not None:
        stmt = stmt.where(time_created >= run_filter.since)
    if run_filter.error_query:
        stmt = stmt.where(matches_error(run_filter.error_query))
    groups = run_filter.status_groups
    if with_status_filter and groups is not None:
        stmt = stmt.where(
            status.in_([s for s in statuses if _STATUS_GROUPS[s.value] in groups])
        )
    return stmt


def _index_runs_of_pair(cc_pair_id: int) -> Select:
    """The pair's index runs under the current search settings. Targeted
    reindexes refetch chosen documents, not the pair, so they are not runs."""
    return (
        select(IndexAttempt)
        .join(SearchSettings)
        .where(
            IndexAttempt.connector_credential_pair_id == cc_pair_id,
            IndexAttempt.targeted_reindex_job_id.is_(None),
            SearchSettings.status == IndexModelStatus.PRESENT,
        )
    )


def _index_attempt_runs(
    run_filter: CCPairRunFilter, with_status_filter: bool
) -> Select:
    stmt = _index_runs_of_pair(run_filter.cc_pair_id)
    own_errors = exists().where(IndexAttemptError.index_attempt_id == IndexAttempt.id)
    unresolved = own_errors.where(IndexAttemptError.is_resolved.is_(False))
    match run_filter.errors:
        case CCPairRunErrors.UNRESOLVED:
            stmt = stmt.where(unresolved)
        case CCPairRunErrors.RESOLVED:
            stmt = stmt.where(own_errors, ~unresolved)
        case None:
            pass

    # A search also reads the attempt's document errors, which carry the
    # message when the attempt itself finished without one.
    def matches_error(query: str) -> ColumnElement[bool]:
        return or_(
            IndexAttempt.error_msg.icontains(query, autoescape=True),
            own_errors.where(
                IndexAttemptError.failure_message.icontains(query, autoescape=True)
            ),
        )

    return _narrowed(
        stmt,
        run_filter,
        IndexAttempt.time_created,
        matches_error,
        IndexAttempt.status,
        IndexingStatus,
        with_status_filter,
    )


def _doc_permission_sync_runs(
    run_filter: CCPairRunFilter, with_status_filter: bool
) -> Select:
    stmt = select(DocPermissionSyncAttempt).where(
        DocPermissionSyncAttempt.connector_credential_pair_id == run_filter.cc_pair_id
    )
    # A sync counts the documents it could not read, and nothing resolves them.
    if run_filter.errors == CCPairRunErrors.UNRESOLVED:
        stmt = stmt.where(DocPermissionSyncAttempt.docs_with_permission_errors > 0)
    elif run_filter.errors == CCPairRunErrors.RESOLVED:
        stmt = stmt.where(false())
    return _narrowed(
        stmt,
        run_filter,
        DocPermissionSyncAttempt.time_created,
        lambda query: DocPermissionSyncAttempt.error_message.icontains(
            query, autoescape=True
        ),
        DocPermissionSyncAttempt.status,
        PermissionSyncStatus,
        with_status_filter,
    )


def _group_sync_runs(run_filter: CCPairRunFilter, with_status_filter: bool) -> Select:
    stmt = select(ExternalGroupPermissionSyncAttempt).where(
        relevant_external_group_sync_attempts_filter(
            run_filter.cc_pair_id, run_filter.source
        )
    )
    # A group sync records no per-item errors, so it either fails or succeeds.
    if run_filter.errors is not None:
        stmt = stmt.where(false())
    return _narrowed(
        stmt,
        run_filter,
        ExternalGroupPermissionSyncAttempt.time_created,
        lambda query: ExternalGroupPermissionSyncAttempt.error_message.icontains(
            query, autoescape=True
        ),
        ExternalGroupPermissionSyncAttempt.status,
        PermissionSyncStatus,
        with_status_filter,
    )


def _prune_runs(run_filter: CCPairRunFilter, with_status_filter: bool) -> Select:
    stmt = select(SyncRecord).where(
        SyncRecord.entity_id == run_filter.cc_pair_id,
        SyncRecord.sync_type == SyncType.PRUNING,
    )
    # A prune records no per-document errors, so it either fails or succeeds.
    if run_filter.errors is not None:
        stmt = stmt.where(false())
    return _narrowed(
        stmt,
        run_filter,
        SyncRecord.sync_start_time,
        lambda query: SyncRecord.error_message.icontains(query, autoescape=True),
        SyncRecord.sync_status,
        SyncStatus,
        with_status_filter,
    )


def _report_text(path: str) -> ColumnElement[str]:
    """The values at a JSON path of a run's report, as one text to search."""
    return cast(func.jsonb_path_query_array(CapabilityCheckRun.report, path), Text)


def _check_runs(run_filter: CCPairRunFilter, with_status_filter: bool) -> Select:
    """The pair's connector-scoped check runs. A check that fails is not a
    document error, so the errors filter leaves the kind out."""
    stmt = select(CapabilityCheckRun).where(
        CapabilityCheckRun.credential_id == run_filter.credential_id,
        CapabilityCheckRun.connector_id == run_filter.connector_id,
    )
    if run_filter.errors is not None:
        stmt = stmt.where(false())
    return _narrowed(
        stmt,
        run_filter,
        CapabilityCheckRun.time_created,
        # A completed run keeps its check messages in the report, not in
        # error_message. Only the check names and messages are searched: the
        # findings may be hidden from the response, so they stay out of it.
        lambda query: or_(
            CapabilityCheckRun.error_message.icontains(query, autoescape=True),
            _report_text("$.check_results[*].display_name").icontains(
                query, autoescape=True
            ),
            _report_text("$.check_results[*].message").icontains(
                query, autoescape=True
            ),
        ),
        CapabilityCheckRun.status,
        CapabilityCheckRunStatus,
        with_status_filter,
    )


def _keyed(stmt: Select, kind: CCPairRunKind) -> Select:
    match kind:
        case CCPairRunKind.INDEXING:
            run_id, time_created = IndexAttempt.id, IndexAttempt.time_created
        case CCPairRunKind.DOC_PERMISSION_SYNC:
            run_id = DocPermissionSyncAttempt.id
            time_created = DocPermissionSyncAttempt.time_created
        case CCPairRunKind.GROUP_SYNC:
            run_id = ExternalGroupPermissionSyncAttempt.id
            time_created = ExternalGroupPermissionSyncAttempt.time_created
        case CCPairRunKind.PRUNING:
            run_id, time_created = SyncRecord.id, SyncRecord.sync_start_time
        case CCPairRunKind.CHECKS:
            run_id = CapabilityCheckRun.id
            time_created = CapabilityCheckRun.time_created
    return stmt.with_only_columns(
        literal(kind.value).label("kind"),
        run_id.label("id"),
        time_created.label("time_created"),
    )


def _runs_of_kind(
    kind: CCPairRunKind, run_filter: CCPairRunFilter, with_status_filter: bool
) -> Select:
    match kind:
        case CCPairRunKind.INDEXING:
            return _index_attempt_runs(run_filter, with_status_filter)
        case CCPairRunKind.DOC_PERMISSION_SYNC:
            return _doc_permission_sync_runs(run_filter, with_status_filter)
        case CCPairRunKind.GROUP_SYNC:
            return _group_sync_runs(run_filter, with_status_filter)
        case CCPairRunKind.PRUNING:
            return _prune_runs(run_filter, with_status_filter)
        case CCPairRunKind.CHECKS:
            return _check_runs(run_filter, with_status_filter)


def _rows_by_id(
    db_session: Session, model: type[_RunT], ids: list[int]
) -> dict[int, _RunT]:
    if not ids:
        return {}
    rows = db_session.scalars(select(model).where(model.id.in_(ids))).all()
    return {row.id: row for row in rows}


def get_cc_pair_run_page(
    db_session: Session,
    kinds: list[CCPairRunKind],
    run_filter: CCPairRunFilter,
    offset: int,
    limit: int,
) -> CCPairRunPage:
    """The page of the pair's runs of ``kinds``, newest first. Ties break on kind
    and id, so rows never swap between pages."""
    order: list[tuple[CCPairRunKind, int]] = []
    if kinds:
        feed = union_all(
            *(_keyed(_runs_of_kind(kind, run_filter, True), kind) for kind in kinds)
        ).subquery()
        rows = db_session.execute(
            select(feed.c.kind, feed.c.id)
            .order_by(feed.c.time_created.desc(), feed.c.kind, feed.c.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        order = [(CCPairRunKind(kind), run_id) for kind, run_id in rows]

    def ids_of(kind: CCPairRunKind) -> list[int]:
        return [run_id for run_kind, run_id in order if run_kind == kind]

    index_attempts = _rows_by_id(
        db_session, IndexAttempt, ids_of(CCPairRunKind.INDEXING)
    )
    doc_permission_syncs = _rows_by_id(
        db_session, DocPermissionSyncAttempt, ids_of(CCPairRunKind.DOC_PERMISSION_SYNC)
    )
    group_syncs = _rows_by_id(
        db_session, ExternalGroupPermissionSyncAttempt, ids_of(CCPairRunKind.GROUP_SYNC)
    )
    prune_runs = _rows_by_id(db_session, SyncRecord, ids_of(CCPairRunKind.PRUNING))
    check_runs = _rows_by_id(
        db_session, CapabilityCheckRun, ids_of(CCPairRunKind.CHECKS)
    )
    loaded = {
        CCPairRunKind.INDEXING: index_attempts.keys(),
        CCPairRunKind.DOC_PERMISSION_SYNC: doc_permission_syncs.keys(),
        CCPairRunKind.GROUP_SYNC: group_syncs.keys(),
        CCPairRunKind.PRUNING: prune_runs.keys(),
        CCPairRunKind.CHECKS: check_runs.keys(),
    }
    return CCPairRunPage(
        # A deletion between the id query and the row loads leaves an id with no row.
        order=[(kind, run_id) for kind, run_id in order if run_id in loaded[kind]],
        index_attempts=index_attempts,
        doc_permission_syncs=doc_permission_syncs,
        group_syncs=group_syncs,
        prune_runs=prune_runs,
        check_runs=check_runs,
    )


def _status_column(kind: CCPairRunKind) -> InstrumentedAttribute:
    match kind:
        case CCPairRunKind.INDEXING:
            return IndexAttempt.status
        case CCPairRunKind.DOC_PERMISSION_SYNC:
            return DocPermissionSyncAttempt.status
        case CCPairRunKind.GROUP_SYNC:
            return ExternalGroupPermissionSyncAttempt.status
        case CCPairRunKind.PRUNING:
            return SyncRecord.sync_status
        case CCPairRunKind.CHECKS:
            return CapabilityCheckRun.status


def count_cc_pair_runs_by_status_group(
    db_session: Session, kinds: list[CCPairRunKind], run_filter: CCPairRunFilter
) -> dict[CCPairRunStatusGroup, int]:
    """Runs of ``kinds`` per status group. The status filter is left out, so the
    counts hold still while one is applied."""
    counts = dict.fromkeys(CCPairRunStatusGroup, 0)
    for kind in kinds:
        runs = (
            _runs_of_kind(kind, run_filter, False)
            .with_only_columns(_status_column(kind).label("status"))
            .subquery()
        )
        for status, count in db_session.execute(
            select(runs.c.status, func.count()).group_by(runs.c.status)
        ).all():
            counts[_STATUS_GROUPS[status.value]] += count
    return counts


def get_index_runs_since(
    db_session: Session, cc_pair_id: int, since: datetime
) -> list[IndexAttempt]:
    """The pair's index runs created or finished since ``since``, plus any
    still active, oldest first. Attempts from before ``time_finished`` existed
    end at their last heartbeat check. ``time_updated`` is left out of the
    window because checkpoint cleanup touches old attempts days later."""
    stmt = (
        _index_runs_of_pair(cc_pair_id)
        .where(
            or_(
                IndexAttempt.time_created >= since,
                func.coalesce(
                    IndexAttempt.time_finished, IndexAttempt.last_heartbeat_time
                )
                >= since,
                IndexAttempt.status.in_(
                    [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                ),
            )
        )
        .order_by(IndexAttempt.time_created)
    )
    return list(db_session.scalars(stmt).all())
