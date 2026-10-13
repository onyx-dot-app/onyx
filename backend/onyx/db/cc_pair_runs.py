"""Queries behind a pair's run history. Each kind of run (index attempts,
document permission syncs, group syncs) is windowed and searched the same way,
and one union pages every kind newest first, so no page loads the runs before it."""

from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, literal, select, union_all
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import (
    CCPairRunKind,
    CCPairRunStatusGroup,
    IndexingStatus,
    IndexModelStatus,
    PermissionSyncStatus,
)
from onyx.db.models import (
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    SearchSettings,
)
from onyx.db.permission_sync_attempt import (
    relevant_external_group_sync_attempts_filter,
)

# Keyed by value, so every PermissionSyncStatus value must also be an
# IndexingStatus value.
_STATUS_GROUPS: dict[str, CCPairRunStatusGroup] = {
    IndexingStatus.NOT_STARTED.value: CCPairRunStatusGroup.RUNNING,
    IndexingStatus.IN_PROGRESS.value: CCPairRunStatusGroup.RUNNING,
    IndexingStatus.SUCCESS.value: CCPairRunStatusGroup.SUCCEEDED,
    IndexingStatus.COMPLETED_WITH_ERRORS.value: CCPairRunStatusGroup.SUCCEEDED,
    IndexingStatus.FAILED.value: CCPairRunStatusGroup.FAILED,
    IndexingStatus.CANCELED.value: CCPairRunStatusGroup.CANCELED,
    IndexingStatus.INTERRUPTED.value: CCPairRunStatusGroup.CANCELED,
}

_StatusT = TypeVar("_StatusT", IndexingStatus, PermissionSyncStatus)
_RunT = TypeVar(
    "_RunT", IndexAttempt, DocPermissionSyncAttempt, ExternalGroupPermissionSyncAttempt
)


class CCPairRunFilter(BaseModel):
    """What narrows a pair's runs. ``None`` leaves that axis open."""

    cc_pair_id: int
    source: DocumentSource
    since: datetime | None
    error_query: str | None
    status_groups: set[CCPairRunStatusGroup] | None


class CCPairRunPage(BaseModel):
    """One page of runs: their order as (kind, id), and each kind's rows by id."""

    # ORM rows ride inside, as in db/projects.py
    model_config = ConfigDict(arbitrary_types_allowed=True)

    order: list[tuple[CCPairRunKind, int]]
    index_attempts: dict[int, IndexAttempt]
    doc_permission_syncs: dict[int, DocPermissionSyncAttempt]
    group_syncs: dict[int, ExternalGroupPermissionSyncAttempt]


def _narrowed(
    stmt: Select,
    run_filter: CCPairRunFilter,
    time_created: InstrumentedAttribute[datetime],
    error_message: InstrumentedAttribute[str | None],
    status: InstrumentedAttribute[_StatusT],
    statuses: type[_StatusT],
    with_status_filter: bool,
) -> Select:
    if run_filter.since is not None:
        stmt = stmt.where(time_created >= run_filter.since)
    if run_filter.error_query:
        stmt = stmt.where(
            error_message.icontains(run_filter.error_query, autoescape=True)
        )
    groups = run_filter.status_groups
    if with_status_filter and groups is not None:
        stmt = stmt.where(
            status.in_([s for s in statuses if _STATUS_GROUPS[s.value] in groups])
        )
    return stmt


def _index_attempt_runs(
    run_filter: CCPairRunFilter, with_status_filter: bool
) -> Select:
    # Targeted reindexes refetch chosen documents, not the pair, so they are not runs.
    stmt = (
        select(IndexAttempt)
        .join(SearchSettings)
        .where(
            IndexAttempt.connector_credential_pair_id == run_filter.cc_pair_id,
            IndexAttempt.targeted_reindex_job_id.is_(None),
            SearchSettings.status == IndexModelStatus.PRESENT,
        )
    )
    return _narrowed(
        stmt,
        run_filter,
        IndexAttempt.time_created,
        IndexAttempt.error_msg,
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
    return _narrowed(
        stmt,
        run_filter,
        DocPermissionSyncAttempt.time_created,
        DocPermissionSyncAttempt.error_message,
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
    return _narrowed(
        stmt,
        run_filter,
        ExternalGroupPermissionSyncAttempt.time_created,
        ExternalGroupPermissionSyncAttempt.error_message,
        ExternalGroupPermissionSyncAttempt.status,
        PermissionSyncStatus,
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

    return CCPairRunPage(
        order=order,
        index_attempts=_rows_by_id(
            db_session, IndexAttempt, ids_of(CCPairRunKind.INDEXING)
        ),
        doc_permission_syncs=_rows_by_id(
            db_session,
            DocPermissionSyncAttempt,
            ids_of(CCPairRunKind.DOC_PERMISSION_SYNC),
        ),
        group_syncs=_rows_by_id(
            db_session,
            ExternalGroupPermissionSyncAttempt,
            ids_of(CCPairRunKind.GROUP_SYNC),
        ),
    )


def count_cc_pair_runs_by_status_group(
    db_session: Session, kinds: list[CCPairRunKind], run_filter: CCPairRunFilter
) -> dict[CCPairRunStatusGroup, int]:
    """Runs of ``kinds`` per status group. The status filter is left out, so the
    counts hold still while one is applied."""
    counts = dict.fromkeys(CCPairRunStatusGroup, 0)
    for kind in kinds:
        runs = _runs_of_kind(kind, run_filter, False).subquery()
        for status, count in db_session.execute(
            select(runs.c.status, func.count()).group_by(runs.c.status)
        ).all():
            counts[_STATUS_GROUPS[status.value]] += count
    return counts
