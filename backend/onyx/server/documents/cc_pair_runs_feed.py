"""One page of a run feed, as a pair's own feed and the fleet's both read it:
the rows, their API items, and the status counts the filter leaves alone."""

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import identify_connector_class
from onyx.connectors.interfaces import Resolver
from onyx.connectors.models import InputType
from onyx.db.cc_pair_run_resolution import get_resolution_times
from onyx.db.cc_pair_runs import (
    count_cc_pair_runs_by_status_group,
    get_cc_pair_run_page,
)
from onyx.db.cc_pair_runs_models import CCPairRunFilter, CCPairRunPage
from onyx.db.enums import CCPairRunKind
from onyx.db.index_attempt import (
    get_error_counts_for_index_attempts,
    get_open_doc_error_counts_for_index_attempts,
)
from onyx.server.documents.models import (
    CCPairChecksRun,
    CCPairDocPermissionSyncRun,
    CCPairGroupSyncRun,
    CCPairIndexRun,
    CCPairPruneRun,
    CCPairRun,
    CheckRunSnapshot,
    DocPermissionSyncAttemptSnapshot,
    ExternalGroupSyncAttemptSnapshot,
    IndexAttemptSnapshot,
    PruneRunSnapshot,
    RunFeed,
)


def connector_supports_targeted_reindex(
    source: DocumentSource, input_type: InputType
) -> bool:
    try:
        return issubclass(identify_connector_class(source, input_type), Resolver)
    except Exception:
        return False


def run_item(
    kind: CCPairRunKind,
    run_id: int,
    page: CCPairRunPage,
    error_counts: dict[int, int],
    open_counts: dict[int, int],
) -> CCPairRun:
    match kind:
        case CCPairRunKind.INDEXING:
            attempt = page.index_attempts[run_id]
            return CCPairIndexRun(
                time_created=attempt.time_created,
                attempt=IndexAttemptSnapshot.from_index_attempt_db_model(
                    attempt,
                    error_count=error_counts.get(run_id, 0),
                    open_doc_error_count=open_counts.get(run_id, 0),
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
        case CCPairRunKind.PRUNING:
            prune = page.prune_runs[run_id]
            return CCPairPruneRun(
                time_created=prune.sync_start_time,
                attempt=PruneRunSnapshot.from_sync_record(prune),
            )
        case CCPairRunKind.CHECKS:
            check_run = page.check_runs[run_id]
            return CCPairChecksRun(
                time_created=check_run.time_created,
                attempt=CheckRunSnapshot.from_check_run(check_run),
            )


def fetch_run_feed(
    db_session: Session,
    kinds: list[CCPairRunKind],
    run_filter: CCPairRunFilter,
    page_num: int,
    page_size: int,
) -> RunFeed:
    """The page of runs of ``kinds`` under ``run_filter``, newest first."""
    page = get_cc_pair_run_page(
        db_session,
        kinds,
        run_filter,
        offset=page_num * page_size,
        limit=page_size,
    )
    error_counts = get_error_counts_for_index_attempts(
        db_session, list(page.index_attempts)
    )
    open_counts = get_open_doc_error_counts_for_index_attempts(
        db_session, list(page.index_attempts)
    )
    resolved_at = get_resolution_times(db_session, page.order)
    status_counts = count_cc_pair_runs_by_status_group(db_session, kinds, run_filter)
    groups = run_filter.status_groups
    return RunFeed(
        page=page,
        items=[
            run_item(kind, run_id, page, error_counts, open_counts).model_copy(
                update={"resolved_at": resolved_at.get((kind, run_id))}
            )
            for kind, run_id in page.order
        ],
        total_items=sum(
            count
            for group, count in status_counts.items()
            if groups is None or group in groups
        ),
        status_counts=status_counts,
    )
