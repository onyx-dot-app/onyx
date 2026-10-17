"""Queries behind a pair's run history. Each kind of run (index attempts,
document permission syncs, group syncs, prunes, connector checks) is windowed
and searched the same way, and one union pages every kind newest first, so no
page loads the runs before it."""

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    cast,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased

from onyx.db.cc_pair_run_resolution import run_is_resolved
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
    CCPairRunResolution,
    Connector,
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
    SyncRecord,
)
from onyx.db.permission_sync_attempt import (
    relevant_external_group_sync_attempts_filter,
    source_group_sync_is_cc_pair_agnostic,
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


def _later(
    newer_time: InstrumentedAttribute[datetime],
    newer_id: InstrumentedAttribute[int],
    time_created: InstrumentedAttribute[datetime],
    run_id: InstrumentedAttribute[int],
) -> ColumnElement[bool]:
    """Whether a run comes after another in the feed's newest-first order."""
    return or_(
        newer_time > time_created, and_(newer_time == time_created, newer_id > run_id)
    )


def _no_item_errors(run_filter: CCPairRunFilter) -> ColumnElement[bool] | None:
    """The ``errors`` filter for a kind that records no per-item errors."""
    if run_filter.errors in (None, CCPairRunErrors.NONE):
        return None
    return false()


def _narrowed(
    stmt: Select,
    run_filter: CCPairRunFilter,
    time_created: InstrumentedAttribute[datetime],
    matches_error: Callable[[str], ColumnElement[bool]],
    status: InstrumentedAttribute[_StatusT],
    statuses: type[_StatusT],
    with_status_filter: bool,
    matches_errors: ColumnElement[bool] | None,
    has_newer_run: ColumnElement[bool],
    is_resolved: ColumnElement[bool],
) -> Select:
    """Applies the filter's shared axes. ``matches_errors`` is the kind's
    ``errors`` filter, ``has_newer_run`` says a newer run of the kind
    follows the run on the same history, and ``is_resolved`` says an admin
    resolved the run."""
    failed = [
        s for s in statuses if _STATUS_GROUPS[s.value] is CCPairRunStatusGroup.FAILED
    ]
    superseded = and_(status.in_(failed), has_newer_run)
    # A True closed-item axis widens what ``errors`` keeps, a False one narrows it.
    widened = [] if matches_errors is None else [matches_errors]
    narrowed: list[ColumnElement[bool]] = []
    for wanted, clause in (
        (run_filter.superseded, superseded),
        (run_filter.resolved, is_resolved),
    ):
        if wanted is True:
            widened.append(clause)
        elif wanted is False:
            narrowed.append(~clause)
    if widened:
        stmt = stmt.where(or_(*widened))
    if narrowed:
        stmt = stmt.where(*narrowed)
    # A run still going belongs to any window or slice, whenever it began.
    active = status.in_(
        [s for s in statuses if _STATUS_GROUPS[s.value] is CCPairRunStatusGroup.RUNNING]
    )
    if run_filter.since is not None:
        stmt = stmt.where(or_(time_created >= run_filter.since, active))
    if run_filter.until is not None:
        stmt = stmt.where(or_(time_created < run_filter.until, active))
    if run_filter.error_query:
        stmt = stmt.where(matches_error(run_filter.error_query))
    groups = run_filter.status_groups
    if with_status_filter and groups is not None:
        stmt = stmt.where(
            status.in_([s for s in statuses if _STATUS_GROUPS[s.value] in groups])
        )
    return stmt


def _index_runs(
    cc_pair_ids: list[int],
    settings_statuses: tuple[IndexModelStatus, ...] = (IndexModelStatus.PRESENT,),
) -> Select:
    """The pairs' index runs under the given search settings, the current ones
    by default. Targeted reindexes refetch chosen documents, not the pair, so
    they are not runs."""
    return (
        select(IndexAttempt)
        .join(SearchSettings)
        .where(
            IndexAttempt.connector_credential_pair_id.in_(cc_pair_ids),
            IndexAttempt.targeted_reindex_job_id.is_(None),
            SearchSettings.status.in_(settings_statuses),
        )
    )


def _group_sync_scope(run_filter: CCPairRunFilter) -> ColumnElement[bool]:
    """A single pair with a source reads the history its source shares. Any
    other scope reads rows by pair id, plus every row of its shared sources."""
    ids = run_filter.cc_pair_ids
    if len(ids) == 1 and run_filter.source is not None:
        return relevant_external_group_sync_attempts_filter(ids[0], run_filter.source)
    own = ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.in_(ids)
    if not run_filter.shared_sources:
        return own
    siblings = (
        select(ConnectorCredentialPair.id)
        .join(ConnectorCredentialPair.connector)
        .where(Connector.source.in_(run_filter.shared_sources))
    )
    return or_(
        own,
        ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.in_(siblings),
    )


def _group_sync_has_newer_run(run_filter: CCPairRunFilter) -> ColumnElement[bool]:
    """A newer group sync on the run's history: its pair's, or its source's when
    the source logs one sync for all its pairs, as ``_group_sync_scope`` reads."""
    ids = run_filter.cc_pair_ids
    if len(ids) == 1 and run_filter.source is not None:
        shared = (
            {run_filter.source}
            if source_group_sync_is_cc_pair_agnostic(run_filter.source)
            else set()
        )
    else:
        shared = run_filter.shared_sources
    run = ExternalGroupPermissionSyncAttempt
    newer = aliased(ExternalGroupPermissionSyncAttempt)
    later = _later(newer.time_created, newer.id, run.time_created, run.id)
    same_pair = newer.connector_credential_pair_id == run.connector_credential_pair_id
    if not shared:
        return exists().where(same_pair, later)
    # Flat joins, since a nested subquery would not correlate to the run.
    run_pair = aliased(ConnectorCredentialPair)
    run_connector = aliased(Connector)
    newer_pair = aliased(ConnectorCredentialPair)
    newer_connector = aliased(Connector)
    return exists().where(
        run_pair.id == run.connector_credential_pair_id,
        run_connector.id == run_pair.connector_id,
        newer_pair.id == newer.connector_credential_pair_id,
        newer_connector.id == newer_pair.connector_id,
        later,
        or_(
            same_pair,
            and_(
                run_connector.source.in_(shared),
                newer_connector.source == run_connector.source,
            ),
        ),
    )


def _index_attempt_runs(
    run_filter: CCPairRunFilter, with_status_filter: bool
) -> Select:
    # The feed also lists a model switch's runs, so their document errors
    # are visible before the swap.
    stmt = _index_runs(
        run_filter.cc_pair_ids,
        (IndexModelStatus.PRESENT, IndexModelStatus.FUTURE),
    )
    own_errors = exists().where(IndexAttemptError.index_attempt_id == IndexAttempt.id)
    unresolved = own_errors.where(IndexAttemptError.is_resolved.is_(False))
    matches_errors: ColumnElement[bool] | None
    match run_filter.errors:
        case CCPairRunErrors.UNRESOLVED:
            matches_errors = unresolved
        case CCPairRunErrors.RESOLVED:
            matches_errors = and_(own_errors, ~unresolved)
        case CCPairRunErrors.NONE:
            matches_errors = ~own_errors
        case None:
            matches_errors = None
    # A run under another model or a targeted reindex leaves this model's
    # failure open.
    newer = aliased(IndexAttempt)
    has_newer_run = exists().where(
        newer.connector_credential_pair_id == IndexAttempt.connector_credential_pair_id,
        newer.search_settings_id == IndexAttempt.search_settings_id,
        newer.targeted_reindex_job_id.is_(None),
        _later(
            newer.time_created, newer.id, IndexAttempt.time_created, IndexAttempt.id
        ),
    )

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
        matches_errors,
        has_newer_run,
        run_is_resolved(CCPairRunKind.INDEXING, IndexAttempt.id),
    )


def _doc_permission_sync_runs(
    run_filter: CCPairRunFilter, with_status_filter: bool
) -> Select:
    stmt = select(DocPermissionSyncAttempt).where(
        DocPermissionSyncAttempt.connector_credential_pair_id.in_(
            run_filter.cc_pair_ids
        )
    )
    # A sync counts the documents it could not read, and nothing resolves them.
    unreadable = func.coalesce(DocPermissionSyncAttempt.docs_with_permission_errors, 0)
    matches_errors: ColumnElement[bool] | None
    match run_filter.errors:
        case CCPairRunErrors.UNRESOLVED:
            matches_errors = unreadable > 0
        case CCPairRunErrors.RESOLVED:
            matches_errors = false()
        case CCPairRunErrors.NONE:
            matches_errors = unreadable == 0
        case None:
            matches_errors = None
    newer = aliased(DocPermissionSyncAttempt)
    has_newer_run = exists().where(
        newer.connector_credential_pair_id
        == DocPermissionSyncAttempt.connector_credential_pair_id,
        _later(
            newer.time_created,
            newer.id,
            DocPermissionSyncAttempt.time_created,
            DocPermissionSyncAttempt.id,
        ),
    )
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
        matches_errors,
        has_newer_run,
        run_is_resolved(CCPairRunKind.DOC_PERMISSION_SYNC, DocPermissionSyncAttempt.id),
    )


def _group_sync_runs(run_filter: CCPairRunFilter, with_status_filter: bool) -> Select:
    stmt = select(ExternalGroupPermissionSyncAttempt).where(
        _group_sync_scope(run_filter)
    )
    # A group sync records no per-item errors, so it either fails or succeeds.
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
        _no_item_errors(run_filter),
        _group_sync_has_newer_run(run_filter),
        run_is_resolved(
            CCPairRunKind.GROUP_SYNC, ExternalGroupPermissionSyncAttempt.id
        ),
    )


def _prune_runs(run_filter: CCPairRunFilter, with_status_filter: bool) -> Select:
    stmt = select(SyncRecord).where(
        SyncRecord.entity_id.in_(run_filter.cc_pair_ids),
        SyncRecord.sync_type == SyncType.PRUNING,
    )
    newer = aliased(SyncRecord)
    has_newer_run = exists().where(
        newer.entity_id == SyncRecord.entity_id,
        newer.sync_type == SyncType.PRUNING,
        _later(
            newer.sync_start_time, newer.id, SyncRecord.sync_start_time, SyncRecord.id
        ),
    )
    # A prune records no per-document errors, so it either fails or succeeds.
    return _narrowed(
        stmt,
        run_filter,
        SyncRecord.sync_start_time,
        lambda query: SyncRecord.error_message.icontains(query, autoescape=True),
        SyncRecord.sync_status,
        SyncStatus,
        with_status_filter,
        _no_item_errors(run_filter),
        has_newer_run,
        run_is_resolved(CCPairRunKind.PRUNING, SyncRecord.id),
    )


def _report_text(path: str) -> ColumnElement[str]:
    """The values at a JSON path of a run's report, as one text to search."""
    return cast(func.jsonb_path_query_array(CapabilityCheckRun.report, path), Text)


def _check_runs(run_filter: CCPairRunFilter, with_status_filter: bool) -> Select:
    """The pairs' connector-scoped check runs, keyed by each pair's credential
    and connector. A check that fails is not a document error, so only the
    open and resolved error filters leave the kind out."""
    stmt = (
        select(CapabilityCheckRun)
        .join(
            ConnectorCredentialPair,
            and_(
                ConnectorCredentialPair.credential_id
                == CapabilityCheckRun.credential_id,
                ConnectorCredentialPair.connector_id == CapabilityCheckRun.connector_id,
            ),
        )
        .where(ConnectorCredentialPair.id.in_(run_filter.cc_pair_ids))
    )
    newer = aliased(CapabilityCheckRun)
    has_newer_run = exists().where(
        newer.credential_id == CapabilityCheckRun.credential_id,
        newer.connector_id == CapabilityCheckRun.connector_id,
        _later(
            newer.time_created,
            newer.id,
            CapabilityCheckRun.time_created,
            CapabilityCheckRun.id,
        ),
    )
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
        _no_item_errors(run_filter),
        has_newer_run,
        run_is_resolved(CCPairRunKind.CHECKS, CapabilityCheckRun.id),
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


def _id_and_pair_columns(
    kind: CCPairRunKind,
) -> tuple[
    InstrumentedAttribute[int],
    InstrumentedAttribute[int] | InstrumentedAttribute[int | None],
]:
    match kind:
        case CCPairRunKind.INDEXING:
            return IndexAttempt.id, IndexAttempt.connector_credential_pair_id
        case CCPairRunKind.DOC_PERMISSION_SYNC:
            return (
                DocPermissionSyncAttempt.id,
                DocPermissionSyncAttempt.connector_credential_pair_id,
            )
        case CCPairRunKind.GROUP_SYNC:
            return (
                ExternalGroupPermissionSyncAttempt.id,
                ExternalGroupPermissionSyncAttempt.connector_credential_pair_id,
            )
        case CCPairRunKind.PRUNING:
            return SyncRecord.id, SyncRecord.entity_id
        case CCPairRunKind.CHECKS:
            # The check runs' query joins the pair on credential and connector.
            return CapabilityCheckRun.id, ConnectorCredentialPair.id


def get_resolvable_runs(
    db_session: Session,
    kinds: list[CCPairRunKind],
    run_filter: CCPairRunFilter,
    runs: list[tuple[CCPairRunKind, int]],
) -> dict[tuple[CCPairRunKind, int], int]:
    """The runs among ``runs`` in the feed of ``kinds`` that failed or hold
    open errors, each with the pair it ran on. Only those have something to
    resolve."""
    found: dict[tuple[CCPairRunKind, int], int] = {}
    open_items = (
        run_filter.model_copy(update={"status_groups": {CCPairRunStatusGroup.FAILED}}),
        run_filter.model_copy(update={"errors": CCPairRunErrors.UNRESOLVED}),
    )
    for kind in kinds:
        ids = [run_id for run_kind, run_id in runs if run_kind == kind]
        if not ids:
            continue
        run_id, pair_id = _id_and_pair_columns(kind)
        for narrowed in open_items:
            stmt = (
                _runs_of_kind(kind, narrowed, True)
                .with_only_columns(run_id, pair_id)
                .where(run_id.in_(ids))
            )
            for found_id, found_pair in db_session.execute(stmt).all():
                found[(kind, found_id)] = found_pair
    return found


def count_matching_runs(
    db_session: Session, kinds: list[CCPairRunKind], run_filter: CCPairRunFilter
) -> int:
    """How many runs of ``kinds`` the filter keeps, which is what
    ``resolve_matching_runs__no_commit`` marks for the same filter."""
    total = 0
    for kind in kinds:
        matching = _runs_of_kind(kind, run_filter, True).subquery()
        total += db_session.scalar(select(func.count()).select_from(matching)) or 0
    return total


def resolve_matching_runs__no_commit(
    db_session: Session,
    kinds: list[CCPairRunKind],
    run_filter: CCPairRunFilter,
    user_id: UUID | None,
) -> dict[int, int]:
    """Marks every run of ``kinds`` the filter keeps resolved, one INSERT from
    SELECT per kind, and returns how many it marked per pair. A run resolved
    before keeps its first resolution and is not counted."""
    resolved: Counter[int] = Counter()
    for kind in kinds:
        run_id, pair_id = _id_and_pair_columns(kind)
        matching = _runs_of_kind(kind, run_filter, True).with_only_columns(
            literal(kind.value),
            run_id,
            pair_id,
            # Typed, since Postgres reads an untyped NULL in a SELECT as text.
            cast(literal(user_id, PGUUID(as_uuid=True)), PGUUID(as_uuid=True)),
        )
        stmt = (
            insert(CCPairRunResolution)
            .from_select(
                ["run_kind", "attempt_id", "cc_pair_id", "resolved_by_user_id"],
                matching,
            )
            .on_conflict_do_nothing(index_elements=["run_kind", "attempt_id"])
            .returning(CCPairRunResolution.cc_pair_id)
        )
        resolved.update(db_session.scalars(stmt).all())
    return dict(resolved)


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


def count_pairs_indexing(db_session: Session, cc_pair_ids: list[int]) -> int:
    """How many of the pairs have an index run in progress, backfills included,
    as the throughput chart counts them."""
    running = (
        _index_runs(cc_pair_ids)
        .where(IndexAttempt.status == IndexingStatus.IN_PROGRESS)
        .subquery()
    )
    stmt = select(func.count(func.distinct(running.c.connector_credential_pair_id)))
    return db_session.scalar(stmt) or 0


def get_index_runs_since(
    db_session: Session, cc_pair_ids: list[int], since: datetime
) -> list[IndexAttempt]:
    """The pairs' index runs created or finished since ``since``, plus any
    still active, oldest first. Attempts from before ``time_finished`` existed
    end at their last heartbeat check. ``time_updated`` is left out of the
    window because checkpoint cleanup touches old attempts days later."""
    stmt = (
        _index_runs(cc_pair_ids)
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
