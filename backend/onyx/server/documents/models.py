from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    model_validator,
)

from onyx.auth.permission_projection import cc_pair_permissions
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.findings_setting import (
    hide_findings_if_disabled,
)
from onyx.connectors.capability_checks.indexing_hold_models import IndexingHold
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CredentialCapabilityReport,
)
from onyx.connectors.connector_config import CredentialBinding
from onyx.connectors.credential_families import to_source_credential_json
from onyx.connectors.models import InputType
from onyx.db.backfill_models import PendingBackfill
from onyx.db.cc_pair_runs_models import CCPairRunPage
from onyx.db.enums import (
    AccessType,
    CapabilityCheckRunStatus,
    CapabilityCheckTrigger,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    ConnectorManageRole,
    HierarchyNodeType,
    PermissionSyncStatus,
    ProcessingMode,
    SyncStatus,
)
from onyx.db.index_attempt_metrics_models import (
    STAGE_SCOPE,
    IndexAttemptStage,
    StageScope,
)
from onyx.db.models import (
    CapabilityCheckRun,
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptStageMetric,
    IndexingStatus,
    SyncRecord,
    TaskStatus,
)
from onyx.db.models import Document as DbDocument
from onyx.server.federated.models import FederatedConnectorStatus
from onyx.utils.encryption import mask_credential_dict
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

logger = setup_logger()


class DocumentSyncStatus(BaseModel):
    doc_id: str
    last_synced: datetime | None
    last_modified: datetime | None

    @classmethod
    def from_model(cls, doc: DbDocument) -> "DocumentSyncStatus":
        return DocumentSyncStatus(
            doc_id=doc.id,
            last_synced=doc.last_synced,
            last_modified=doc.last_modified,
        )


class DocumentInfo(BaseModel):
    num_chunks: int
    num_tokens: int


class ChunkInfo(BaseModel):
    content: str
    num_tokens: int


class IndexedSourcesResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    sources: list[DocumentSource]


class DeletionAttemptSnapshot(BaseModel):
    connector_id: int
    credential_id: int
    status: TaskStatus


class ConnectorBase(BaseModel):
    name: str
    source: DocumentSource
    input_type: InputType
    connector_specific_config: dict[str, Any]
    # In seconds, None for one time index with no refresh
    refresh_freq: int | None = None
    prune_freq: int | None = None
    # In seconds, None runs the connector checks only on request
    check_freq: int | None = None
    indexing_start: datetime | None = None


class ConnectorUpdateRequest(ConnectorBase):
    access_type: AccessType
    groups: list[int] = Field(default_factory=list)

    def to_connector_base(self) -> ConnectorBase:
        # Only the request's own fields, so an omitted check_freq stays omitted
        # (update_connector keeps the stored schedule) instead of becoming null.
        return ConnectorBase(
            **self.model_dump(exclude_unset=True, exclude={"access_type", "groups"})
        )


class ConnectorSnapshot(ConnectorBase):
    id: int
    credential_ids: list[int]
    time_created: datetime
    time_updated: datetime
    source: DocumentSource

    @classmethod
    def from_connector_db_model(
        cls, connector: Connector, credential_ids: list[int] | None = None
    ) -> "ConnectorSnapshot":
        return ConnectorSnapshot(
            id=connector.id,
            name=connector.name,
            source=connector.source,
            input_type=connector.input_type,
            connector_specific_config=connector.connector_specific_config,
            refresh_freq=connector.refresh_freq,
            prune_freq=connector.prune_freq,
            check_freq=connector.check_freq,
            credential_ids=(
                credential_ids
                or [association.credential.id for association in connector.credentials]
            ),
            indexing_start=connector.indexing_start,
            time_created=connector.time_created,
            time_updated=connector.time_updated,
        )


class CredentialSwapRequest(BaseModel):
    new_credential_id: int
    connector_id: int
    access_type: AccessType


class CredentialDataUpdateRequest(BaseModel):
    name: str
    credential_json: dict[str, Any]


class CredentialBase(BaseModel):
    credential_json: dict[str, Any]
    # if `true`, then all Admins will have access to the credential
    admin_public: bool
    source: DocumentSource
    name: str | None = None
    curator_public: bool = False
    groups: list[int] = Field(default_factory=list)


class CredentialSnapshot(CredentialBase):
    id: int
    user_id: UUID | None
    user_email: str | None = None
    # The creator's display name; None when they never set one.
    user_personal_name: str | None = None
    time_created: datetime
    time_updated: datetime
    # Whether the requesting user owns the credential. None when the response
    # does not say (snapshots nested in pair, group and document-set views).
    is_owner: bool | None = None

    @classmethod
    def from_credential_db_model(
        cls,
        credential: Credential,
        *,
        mask_credential_prefix: bool,
        view_source: DocumentSource | None = None,
        viewer_id: UUID | None = None,
        group_ids: list[int] | None = None,
    ) -> Self:
        """``view_source`` picks the keys ``credential_json`` is shown in: a
        family credential listed for another source of its family is shown in
        that source's keys. Defaults to the credential's own source.

        ``viewer_id`` fills ``is_owner``. ``group_ids`` are the groups the
        credential is shared with (``fetch_credential_group_ids``); the
        credential endpoints pass them, nested snapshots leave ``groups``
        empty."""
        source = credential.source or DocumentSource.NOT_APPLICABLE
        stored_json = (
            credential.credential_json.get_value(apply_mask=False)
            if credential.credential_json
            else {}
        )
        try:
            credential_json_value = to_source_credential_json(
                view_source or source, stored_json
            )
        except ValueError:
            # One unreadable row (e.g. its source left the family registry) must
            # not fail a whole credential listing.
            logger.warning(
                "Showing credential %s in its stored shape: it cannot be read as %s.",
                credential.id,
                (view_source or source).value,
            )
            credential_json_value = stored_json
        if mask_credential_prefix:
            credential_json_value = mask_credential_dict(credential_json_value)

        return cls(
            id=credential.id,
            credential_json=credential_json_value,
            user_id=credential.user_id,
            user_email=credential.user.email if credential.user else None,
            user_personal_name=(
                credential.user.personal_name if credential.user else None
            ),
            admin_public=credential.admin_public,
            time_created=credential.time_created,
            time_updated=credential.time_updated,
            source=source,
            name=credential.name,
            curator_public=credential.curator_public,
            groups=group_ids or [],
            is_owner=(
                None
                if viewer_id is None
                else credential.user_id is not None and credential.user_id == viewer_id
            ),
        )


class CredentialUsage(BaseModel):
    """A connector that uses a credential, as a hint for picking a credential."""

    cc_pair_id: int
    cc_pair_name: str | None
    connector_id: int
    source: DocumentSource
    # None when the source has no binding model or the stored config does not
    # match it.
    credential_binding: SerializeAsAny[CredentialBinding] | None


class SimilarCredentialSnapshot(CredentialSnapshot):
    # Only connectors the requesting user can manage.
    usages: list[CredentialUsage] = Field(default_factory=list)


class IndexAttemptSnapshot(BaseModel):
    id: int
    status: IndexingStatus | None
    from_beginning: bool
    new_docs_indexed: int  # only includes completely new docs
    total_docs_indexed: int  # includes docs that are updated
    docs_removed_from_index: int
    error_msg: str | None
    error_count: int
    # Unresolved document-level errors, the ones a targeted reindex can retry.
    open_doc_error_count: int
    full_exception_trace: str | None
    time_started: str | None
    time_updated: str
    # When a finished attempt ended. `time_updated` moves days later when
    # checkpoint cleanup touches the row, so it is no stand-in.
    time_finished: str | None
    poll_range_start: datetime | None = None
    poll_range_end: datetime | None = None
    # A one-off run over poll_range_start..poll_range_end outside the pair's
    # incremental cursor; it does not drive the pair's status.
    is_backfill: bool = False
    # Indexed under the FUTURE search settings of a running model switch.
    is_new_model: bool = False

    @classmethod
    def from_index_attempt_db_model(
        cls, index_attempt: IndexAttempt, error_count: int, open_doc_error_count: int
    ) -> "IndexAttemptSnapshot":
        # Attempts from before time_finished existed end at their last heartbeat
        # check, and at their start when they never reached one.
        finished = (
            index_attempt.time_finished
            or index_attempt.last_heartbeat_time
            or index_attempt.time_started
            or index_attempt.time_created
            if index_attempt.is_finished()
            else None
        )
        return IndexAttemptSnapshot(
            id=index_attempt.id,
            status=index_attempt.status,
            from_beginning=index_attempt.from_beginning,
            new_docs_indexed=index_attempt.new_docs_indexed or 0,
            total_docs_indexed=index_attempt.total_docs_indexed or 0,
            docs_removed_from_index=index_attempt.docs_removed_from_index or 0,
            error_msg=index_attempt.error_msg,
            error_count=error_count,
            open_doc_error_count=open_doc_error_count,
            full_exception_trace=index_attempt.full_exception_trace,
            time_started=(
                index_attempt.time_started.isoformat()
                if index_attempt.time_started
                else None
            ),
            time_updated=index_attempt.time_updated.isoformat(),
            time_finished=finished.isoformat() if finished else None,
            poll_range_start=index_attempt.poll_range_start,
            poll_range_end=index_attempt.poll_range_end,
            is_new_model=(
                index_attempt.search_settings is not None
                and index_attempt.search_settings.status.is_future()
            ),
            is_backfill=index_attempt.is_backfill,
        )


class IndexAttemptStageMetricSnapshot(BaseModel):
    """Per-stage timing aggregate for a single ``IndexAttempt``.

    ``avg_duration_ms`` and ``std_dev_duration_ms`` are derived at
    serialization time from the stored ``total_duration_ms`` and
    ``m2_duration_ms`` (Welford / Chan accumulator). ``std_dev_duration_ms``
    is undefined for ``event_count <= 1`` and is reported as ``None`` in
    that case so the frontend can render "avg" without "± std dev".
    """

    model_config = ConfigDict(use_enum_values=True)

    stage: IndexAttemptStage
    scope: StageScope
    event_count: int
    total_duration_ms: int
    avg_duration_ms: float | None
    std_dev_duration_ms: float | None
    min_duration_ms: int | None
    max_duration_ms: int | None
    time_first_event: datetime | None
    time_last_event: datetime | None

    @classmethod
    def from_db_model(
        cls, metric: IndexAttemptStageMetric
    ) -> "IndexAttemptStageMetricSnapshot":
        avg = (
            metric.total_duration_ms / metric.event_count
            if metric.event_count > 0
            else None
        )
        std_dev = (
            max(0.0, metric.m2_duration_ms / (metric.event_count - 1)) ** 0.5
            if metric.event_count > 1
            else None
        )
        return IndexAttemptStageMetricSnapshot(
            stage=metric.stage,
            scope=STAGE_SCOPE[metric.stage],
            event_count=metric.event_count,
            total_duration_ms=metric.total_duration_ms,
            avg_duration_ms=avg,
            std_dev_duration_ms=std_dev,
            min_duration_ms=metric.min_duration_ms,
            max_duration_ms=metric.max_duration_ms,
            time_first_event=metric.time_first_event,
            time_last_event=metric.time_last_event,
        )


class IndexAttemptStageMetricsResponse(BaseModel):
    """Per-attempt stage rows (pipeline order) plus the BATCH_UNACCOUNTED residual
    appended last; the frontend re-sorts, so array order isn't load-bearing.
    """

    index_attempt_id: int
    stages: list[IndexAttemptStageMetricSnapshot]


# In-span stages for the residual (BATCH_TOTAL - sum). Excludes pre-span
# stages (QUEUE_WAIT/SETUP/BATCH_LOAD), docfetching, and the aggregates.
_BATCH_TOTAL_COMPONENT_STAGES: frozenset[IndexAttemptStage] = frozenset(
    {
        IndexAttemptStage.DOC_DB_PREPARE,
        IndexAttemptStage.IMAGE_PROCESSING,
        IndexAttemptStage.CHUNKING,
        IndexAttemptStage.CONTEXTUAL_RAG,
        IndexAttemptStage.EMBEDDING,
        IndexAttemptStage.DOC_LOCK_ACQUIRE_WAIT,
        IndexAttemptStage.ENRICHMENT_PREP,
        IndexAttemptStage.COORD_LOCK_ACQUIRE_WAIT,
        IndexAttemptStage.VECTOR_DB_WRITE,
        IndexAttemptStage.POST_INDEX_DB_UPDATE,
        IndexAttemptStage.COORDINATION_UPDATE,
        IndexAttemptStage.FINALIZATION,
        IndexAttemptStage.GC_COLLECT,
    }
)


def synthesize_unaccounted(
    snapshots: list[IndexAttemptStageMetricSnapshot],
) -> IndexAttemptStageMetricSnapshot | None:
    """Residual = BATCH_TOTAL minus in-span component totals, clamped at 0.

    None if BATCH_TOTAL is absent. Uses totals (not averages).
    """
    batch_total = next(
        (s for s in snapshots if s.stage == IndexAttemptStage.BATCH_TOTAL),
        None,
    )
    if batch_total is None:
        return None

    component_total = sum(
        s.total_duration_ms
        for s in snapshots
        if s.stage in _BATCH_TOTAL_COMPONENT_STAGES
    )
    if component_total > batch_total.total_duration_ms:
        # Components > total = double-counting or failed-batch skew; clamp to 0.
        logger.warning(
            "Stage components (%d ms) exceed BATCH_TOTAL (%d ms) for an index "
            "attempt; clamping BATCH_UNACCOUNTED to 0.",
            component_total,
            batch_total.total_duration_ms,
        )
    residual_total = max(0, batch_total.total_duration_ms - component_total)
    event_count = batch_total.event_count
    avg = residual_total / event_count if event_count > 0 else None
    return IndexAttemptStageMetricSnapshot(
        stage=IndexAttemptStage.BATCH_UNACCOUNTED,
        scope=STAGE_SCOPE[IndexAttemptStage.BATCH_UNACCOUNTED],
        event_count=event_count,
        total_duration_ms=residual_total,
        avg_duration_ms=avg,
        std_dev_duration_ms=None,
        min_duration_ms=None,
        max_duration_ms=None,
        time_first_event=batch_total.time_first_event,
        time_last_event=batch_total.time_last_event,
    )


# These are the types currently supported by the pagination hook
# More api endpoints can be refactored and be added here for use with the pagination hook
PaginatedType = TypeVar("PaginatedType", bound=BaseModel)


class DocPermissionSyncAttemptSnapshot(BaseModel):
    id: int
    status: PermissionSyncStatus
    error_message: str | None
    full_exception_trace: str | None
    total_docs_synced: int
    docs_with_permission_errors: int
    time_created: str
    time_started: str | None
    time_finished: str | None

    @classmethod
    def from_doc_permission_sync_attempt_db_model(
        cls, attempt: DocPermissionSyncAttempt
    ) -> "DocPermissionSyncAttemptSnapshot":
        return DocPermissionSyncAttemptSnapshot(
            id=attempt.id,
            status=attempt.status,
            error_message=attempt.error_message,
            full_exception_trace=attempt.full_exception_trace,
            total_docs_synced=attempt.total_docs_synced or 0,
            docs_with_permission_errors=attempt.docs_with_permission_errors or 0,
            time_created=attempt.time_created.isoformat(),
            time_started=(
                attempt.time_started.isoformat() if attempt.time_started else None
            ),
            time_finished=(
                attempt.time_finished.isoformat() if attempt.time_finished else None
            ),
        )


class ExternalGroupSyncAttemptSnapshot(BaseModel):
    id: int
    status: PermissionSyncStatus
    error_message: str | None
    full_exception_trace: str | None
    total_users_processed: int
    total_groups_processed: int
    total_group_memberships_synced: int
    time_created: str
    time_started: str | None
    time_finished: str | None

    @classmethod
    def from_external_group_sync_attempt_db_model(
        cls, attempt: ExternalGroupPermissionSyncAttempt
    ) -> "ExternalGroupSyncAttemptSnapshot":
        return ExternalGroupSyncAttemptSnapshot(
            id=attempt.id,
            status=attempt.status,
            error_message=attempt.error_message,
            full_exception_trace=attempt.full_exception_trace,
            total_users_processed=attempt.total_users_processed or 0,
            total_groups_processed=attempt.total_groups_processed or 0,
            total_group_memberships_synced=attempt.total_group_memberships_synced or 0,
            time_created=attempt.time_created.isoformat(),
            time_started=(
                attempt.time_started.isoformat() if attempt.time_started else None
            ),
            time_finished=(
                attempt.time_finished.isoformat() if attempt.time_finished else None
            ),
        )


class PaginatedReturn(BaseModel, Generic[PaginatedType]):
    items: list[PaginatedType]
    total_items: int


class CCPairIndexRun(BaseModel):
    kind: Literal[CCPairRunKind.INDEXING] = CCPairRunKind.INDEXING
    time_created: datetime
    attempt: IndexAttemptSnapshot
    # When an admin resolved the run. It keeps its status.
    resolved_at: datetime | None = None


class CCPairDocPermissionSyncRun(BaseModel):
    kind: Literal[CCPairRunKind.DOC_PERMISSION_SYNC] = CCPairRunKind.DOC_PERMISSION_SYNC
    time_created: datetime
    attempt: DocPermissionSyncAttemptSnapshot
    # When an admin resolved the run. It keeps its status.
    resolved_at: datetime | None = None


class CCPairGroupSyncRun(BaseModel):
    kind: Literal[CCPairRunKind.GROUP_SYNC] = CCPairRunKind.GROUP_SYNC
    time_created: datetime
    attempt: ExternalGroupSyncAttemptSnapshot
    # When an admin resolved the run. It keeps its status.
    resolved_at: datetime | None = None


class PruneRunSnapshot(BaseModel):
    """One prune of the pair, from its pruning sync record."""

    id: int
    status: SyncStatus
    docs_removed: int
    error_message: str | None
    time_created: str
    time_started: str | None
    time_finished: str | None

    @classmethod
    def from_sync_record(cls, record: SyncRecord) -> "PruneRunSnapshot":
        return cls(
            id=record.id,
            status=record.sync_status,
            docs_removed=record.num_docs_synced,
            error_message=record.error_message,
            time_created=record.sync_start_time.isoformat(),
            time_started=record.sync_start_time.isoformat(),
            time_finished=(
                record.sync_end_time.isoformat() if record.sync_end_time else None
            ),
        )


class CheckRunSnapshot(BaseModel):
    """One run of the pair's connector checks and what it found."""

    id: int
    status: CapabilityCheckRunStatus
    trigger: CapabilityCheckTrigger
    # Empty until the run completes, and for a run that broke.
    check_results: list[CapabilityCheckResult]
    # Why a run broke.
    error_message: str | None
    time_created: str
    time_started: str | None
    time_finished: str | None

    @classmethod
    def from_check_run(cls, run: CapabilityCheckRun) -> "CheckRunSnapshot":
        results: list[CapabilityCheckResult] = []
        if run.report is not None:
            results = CredentialCapabilityReport.model_validate(
                run.report
            ).check_results
        # The history keeps the findings, the response honors the workspace switch.
        hide_findings_if_disabled(results)
        return cls(
            id=run.id,
            status=run.status,
            trigger=run.trigger,
            check_results=results,
            error_message=run.error_message,
            time_created=run.time_created.isoformat(),
            time_started=run.time_created.isoformat(),
            time_finished=(
                run.time_finished.isoformat() if run.time_finished else None
            ),
        )


class CCPairPruneRun(BaseModel):
    kind: Literal[CCPairRunKind.PRUNING] = CCPairRunKind.PRUNING
    time_created: datetime
    attempt: PruneRunSnapshot
    # When an admin resolved the run. It keeps its status.
    resolved_at: datetime | None = None


class CCPairChecksRun(BaseModel):
    kind: Literal[CCPairRunKind.CHECKS] = CCPairRunKind.CHECKS
    time_created: datetime
    attempt: CheckRunSnapshot
    # When an admin resolved the run. It keeps its status.
    resolved_at: datetime | None = None


CCPairRun = Annotated[
    CCPairIndexRun
    | CCPairDocPermissionSyncRun
    | CCPairGroupSyncRun
    | CCPairPruneRun
    | CCPairChecksRun,
    Field(discriminator="kind"),
]


class CCPairRunsResponse(BaseModel):
    """One page of the pair's runs, newest first."""

    items: list[CCPairRun]
    # Runs matching every filter, across the kinds asked for.
    total_items: int
    # The kinds this pair runs, whatever was asked for.
    kinds: list[CCPairRunKind]
    # Per status group, ignoring the status filter, so the counts stay put
    # while one is applied.
    status_counts: dict[CCPairRunStatusGroup, int]


class RunFeed(BaseModel):
    """One page of a run feed, for a pair's own feed and the fleet's: the rows
    for lookups, the items to serve, the runs matching every filter, and the
    counts per status group ignoring the status filter."""

    # ORM rows ride inside, as in db/projects.py
    model_config = ConfigDict(arbitrary_types_allowed=True)

    page: CCPairRunPage
    items: list[CCPairRun]
    total_items: int
    status_counts: dict[CCPairRunStatusGroup, int]


class CCPairThroughputWindow(str, Enum):
    """How far back a throughput chart reaches."""

    HOURS_1 = "1h"
    HOURS_12 = "12h"
    HOURS_24 = "24h"
    DAYS_7 = "7d"

    def duration(self) -> timedelta:
        match self:
            case CCPairThroughputWindow.HOURS_1:
                return timedelta(hours=1)
            case CCPairThroughputWindow.HOURS_12:
                return timedelta(hours=12)
            case CCPairThroughputWindow.HOURS_24:
                return timedelta(hours=24)
            case CCPairThroughputWindow.DAYS_7:
                return timedelta(days=7)


class CCPairThroughputRun(BaseModel):
    started: datetime
    # None while the run is still going.
    ended: datetime | None
    status: IndexingStatus


class CCPairThroughputResponse(BaseModel):
    """A rough estimate of the documents indexed in each equal slice of the
    window, oldest first (each run's total spread evenly over its span, since
    nothing records when a document landed), and the runs that overlap it,
    oldest first."""

    window_start: datetime
    window_end: datetime
    docs_indexed: list[int]
    runs: list[CCPairThroughputRun]


class IndexingOverviewResponse(BaseModel):
    """The pairs the caller can read at a glance: how many run an index now and
    how many are active at all, the documents indexed in the window against the
    documents held, and the window's throughput."""

    indexing_connectors: int
    active_connectors: int
    recent_docs_indexed: int
    total_docs_indexed: int
    throughput: CCPairThroughputResponse


class CCPairRunKey(BaseModel):
    kind: CCPairRunKind
    attempt_id: int


class CCPairRunsResolveRequest(BaseModel):
    runs: list[CCPairRunKey] = Field(max_length=500)


class CCPairRunLevel(str, Enum):
    """An activity panel level that holds open runs."""

    FAILURES = "failures"
    ERRORS = "errors"


class CCPairRunsResolveMatchingRequest(BaseModel):
    """The open runs of one activity level, narrowed as the runs feed narrows them."""

    level: CCPairRunLevel
    q: str | None = Field(default=None, max_length=200)
    since: datetime | None = None
    until: datetime | None = None
    kinds: list[CCPairRunKind] | None = None


class CCPairRunsResolveResponse(BaseModel):
    resolved_count: int


class CCPairRunsResolveMatchingResponse(BaseModel):
    resolved_count: int
    # The pairs that had a run marked, so a client refetches only their feeds.
    cc_pair_ids: list[int]


class CCPairRunsResolvableCountResponse(BaseModel):
    count: int


class CCPairRef(BaseModel):
    """A pair named in a fleet-wide feed."""

    id: int
    name: str
    source: DocumentSource
    # The caller may re-fetch single documents of this pair: they may submit a
    # targeted reindex, operate the pair, and its connector resolves documents.
    can_resolve: bool
    # The caller may mark this pair's runs resolved: they may submit a targeted
    # reindex and operate the pair, whatever the connector supports.
    can_resolve_runs: bool


class IndexingRun(BaseModel):
    """One run in the fleet-wide feed, with the pair it ran on."""

    cc_pair: CCPairRef
    run: CCPairRun


class IndexingRunsResponse(BaseModel):
    """One page of the readable pairs' runs, newest first."""

    items: list[IndexingRun]
    # Runs matching every filter.
    total_items: int
    # Per status group, ignoring the status filter, so the counts stay put
    # while one is applied.
    status_counts: dict[CCPairRunStatusGroup, int]


class IndexingConnectorStatus(str, Enum):
    """How the status page buckets a pair, in the order the list sorts them."""

    INDEXING = "indexing"
    FAILED = "failed"
    PAUSED = "paused"
    SCHEDULED = "scheduled"
    INDEXED = "indexed"


class IndexingConnectorRow(BaseModel):
    """One pair in the status page's list, with its latest index attempt."""

    cc_pair_id: int
    name: str
    source: DocumentSource
    access_type: AccessType
    # The pair's own state, which names the tag for a pair that is deleting,
    # invalid or on its first index. `status` is the bucket.
    cc_pair_status: ConnectorCredentialPairStatus
    status: IndexingConnectorStatus
    creator_email: str | None
    # The owner's display name. Clients fall back to the email when it is unset.
    creator_name: str | None
    docs_indexed: int
    last_success: datetime | None
    latest_index_attempt: IndexAttemptSnapshot | None
    # Place by age in the line of index attempts handed to the queue, from 1,
    # while the latest waits there. The queue serves first runs ahead of
    # repeats, so a repeat can wait a little longer than its place says.
    queue_position: int | None
    # per-action affordance map for the requesting user, from the same access
    # decisions the write guards enforce
    permissions: dict[str, bool]


class IndexingConnectorsResponse(BaseModel):
    """One page of the readable pairs, sorted by status then name."""

    items: list[IndexingConnectorRow]
    # Pairs matching the search and the status filter.
    total_items: int
    # Per status, ignoring the status filter, so the counts stay put while one is applied.
    status_counts: dict[IndexingConnectorStatus, int]
    # Federated connectors have no runs or documents. Admins see them after the
    # pairs on the first page, under the search but outside the status filter.
    federated_connectors: list[FederatedConnectorStatus]


class PendingBackfillSnapshot(BaseModel):
    """A backfill an applied edit requested, until an attempt of it succeeds.
    The beat retries a failed one after ``retry_after``."""

    window_start: datetime
    window_end: datetime
    requested_at: datetime
    # It runs with a config other than the saved one.
    scoped: bool
    attempt_id: int | None
    failure_count: int
    retry_after: datetime | None

    @classmethod
    def from_pending(cls, pending: PendingBackfill) -> "PendingBackfillSnapshot":
        return cls(
            window_start=pending.backfill.window_start,
            window_end=pending.backfill.window_end,
            requested_at=pending.requested_at,
            scoped=pending.backfill.connector_config_override is not None,
            attempt_id=pending.attempt_id,
            failure_count=pending.failure_count,
            retry_after=pending.retry_after,
        )


class HierarchyBreakdownEntry(BaseModel):
    # The id the connector config uses for the node (Confluence: space key,
    # numeric page id). It differs from the stored raw id for Confluence pages.
    raw_node_id: str
    # None when the config names a node that the hierarchy does not have.
    display_name: str | None
    link: str | None
    # Indexed documents of the cc-pair in the node's subtree. None: the config
    # names the node, but no document of the cc-pair is under it.
    doc_count: int | None


class CCPairHierarchyBreakdown(BaseModel):
    """Where a cc-pair's documents come from, by hierarchy node type."""

    nodes_by_type: dict[HierarchyNodeType, list[HierarchyBreakdownEntry]]
    # Indexed documents of the cc-pair that are in no listed node's subtree:
    # documents without a hierarchy parent, or under nodes that are not listed.
    # The rows can overlap (a listed page inside a listed space), so the row
    # counts plus this count can be more than the cc-pair's total.
    other_doc_count: int
    # Config fields whose values the rows list, so the page shows no row for them.
    config_fields: list[str]


class CCPairFullInfo(BaseModel):
    id: int
    name: str
    status: ConnectorCredentialPairStatus
    in_repeated_error_state: bool
    num_docs_indexed: int
    connector: ConnectorSnapshot
    credential: CredentialSnapshot
    number_of_index_attempts: int
    last_index_attempt_status: IndexingStatus | None
    latest_deletion_attempt: DeletionAttemptSnapshot | None
    access_type: AccessType
    # True when the caller may operate the pair (the OPERATE access level)
    is_editable_for_current_user: bool
    # per-action affordance map for the requesting user, from the same access
    # decisions the write guards enforce
    permissions: dict[str, bool]
    deletion_failure_message: str | None
    indexing: bool
    creator: UUID | None
    creator_email: str | None

    # information on syncing/indexing
    last_indexed: datetime | None
    last_pruned: datetime | None
    # accounts for both doc sync and group sync
    last_full_permission_sync: datetime | None
    overall_indexing_speed: float | None
    latest_checkpoint_description: str | None

    # permission sync attempt status
    last_permission_sync_attempt_status: PermissionSyncStatus | None
    permission_syncing: bool
    last_permission_sync_attempt_finished: datetime | None
    last_permission_sync_attempt_error_message: str | None

    # True if this connector's class implements `Resolver.reindex`. The FE
    # uses this to route Resolve-All to targeted reindex vs full reindex.
    supports_targeted_reindex: bool
    # The source names checks of its own, so check runs can be scheduled and
    # listed. A source without them only records the blocking validation.
    has_named_checks: bool

    # Written at create time on the association route but not returned until now,
    # so a client could never refresh or import them.
    groups: list[int]
    auto_sync_options: dict[str, Any] | None
    processing_mode: ProcessingMode

    # Set while the first index attempt waits on the capability checks.
    indexing_hold: IndexingHold | None = None
    pending_backfills: list[PendingBackfillSnapshot]

    @classmethod
    def _get_last_full_permission_sync(
        cls, cc_pair_model: ConnectorCredentialPair
    ) -> datetime | None:
        check_if_source_requires_external_group_sync = fetch_ee_implementation_or_noop(
            "onyx.external_permissions.sync_params",
            "source_requires_external_group_sync",
            noop_return_value=False,
        )
        check_if_source_requires_doc_sync = fetch_ee_implementation_or_noop(
            "onyx.external_permissions.sync_params",
            "source_requires_doc_sync",
            noop_return_value=False,
        )

        needs_group_sync = check_if_source_requires_external_group_sync(
            cc_pair_model.connector.source
        )
        needs_doc_sync = check_if_source_requires_doc_sync(
            cc_pair_model.connector.source
        )

        last_group_sync = (
            cc_pair_model.last_time_external_group_sync
            if needs_group_sync
            else datetime.now(UTC)
        )
        last_doc_sync = (
            cc_pair_model.last_time_perm_sync if needs_doc_sync else datetime.now(UTC)
        )

        # if either is still None at this point, it means sync is necessary but
        # has never completed.
        if last_group_sync is None or last_doc_sync is None:
            return None

        return min(last_group_sync, last_doc_sync)

    @classmethod
    def from_models(
        cls,
        cc_pair_model: ConnectorCredentialPair,
        latest_deletion_attempt: DeletionAttemptSnapshot | None,
        number_of_index_attempts: int,
        last_index_attempt: IndexAttempt | None,
        num_docs_indexed: int,  # not ideal, but this must be computed separately
        is_editable_for_current_user: bool,
        indexing: bool,
        *,
        mask_credential_prefix: bool,
        can_edit: bool,
        is_connectors_admin: bool = False,
        groups: list[int] | None = None,
        last_successful_index_time: datetime | None = None,
        last_permission_sync_attempt_status: PermissionSyncStatus | None = None,
        permission_syncing: bool = False,
        last_permission_sync_attempt_finished: datetime | None = None,
        last_permission_sync_attempt_error_message: str | None = None,
        supports_targeted_reindex: bool = False,
        has_named_checks: bool = False,
        indexing_hold: IndexingHold | None = None,
    ) -> "CCPairFullInfo":
        # figure out if we need to artificially deflate the number of docs indexed.
        # This is required since the total number of docs indexed by a CC Pair is
        # updated before the new docs for an indexing attempt. If we don't do this,
        # there is a mismatch between these two numbers which may confuse users.
        last_indexing_status = last_index_attempt.status if last_index_attempt else None
        if (
            # only need to do this if the last indexing attempt is still in progress
            last_indexing_status == IndexingStatus.IN_PROGRESS
            and number_of_index_attempts == 1
            and last_index_attempt
            and last_index_attempt.new_docs_indexed
        ):
            num_docs_indexed = (
                last_index_attempt.new_docs_indexed if last_index_attempt else 0
            )

        overall_indexing_speed = num_docs_indexed / (
            (
                datetime.now(tz=timezone.utc) - cc_pair_model.connector.time_created
            ).total_seconds()
            / 60
        )

        return cls(
            id=cc_pair_model.id,
            name=cc_pair_model.name,
            status=cc_pair_model.status,
            in_repeated_error_state=cc_pair_model.in_repeated_error_state,
            num_docs_indexed=num_docs_indexed,
            connector=ConnectorSnapshot.from_connector_db_model(
                cc_pair_model.connector,
                credential_ids=[cc_pair_model.credential_id],
            ),
            credential=CredentialSnapshot.from_credential_db_model(
                cc_pair_model.credential,
                mask_credential_prefix=mask_credential_prefix,
            ),
            number_of_index_attempts=number_of_index_attempts,
            last_index_attempt_status=last_indexing_status,
            latest_deletion_attempt=latest_deletion_attempt,
            access_type=cc_pair_model.access_type,
            is_editable_for_current_user=is_editable_for_current_user,
            permissions=cc_pair_permissions(
                can_operate=is_editable_for_current_user,
                can_edit=can_edit,
                is_connectors_admin=is_connectors_admin,
            ),
            deletion_failure_message=cc_pair_model.deletion_failure_message,
            indexing=indexing,
            creator=cc_pair_model.creator_id,
            creator_email=(
                cc_pair_model.creator.email if cc_pair_model.creator else None
            ),
            last_indexed=last_successful_index_time,
            last_pruned=cc_pair_model.last_pruned,
            last_full_permission_sync=cls._get_last_full_permission_sync(cc_pair_model),
            overall_indexing_speed=overall_indexing_speed,
            latest_checkpoint_description=None,
            last_permission_sync_attempt_status=last_permission_sync_attempt_status,
            permission_syncing=permission_syncing,
            last_permission_sync_attempt_finished=last_permission_sync_attempt_finished,
            last_permission_sync_attempt_error_message=last_permission_sync_attempt_error_message,
            supports_targeted_reindex=supports_targeted_reindex,
            has_named_checks=has_named_checks,
            groups=groups or [],
            auto_sync_options=cc_pair_model.auto_sync_options,
            processing_mode=cc_pair_model.processing_mode,
            indexing_hold=indexing_hold,
            pending_backfills=[
                PendingBackfillSnapshot.from_pending(pending)
                for pending in cc_pair_model.pending_backfills
            ],
        )


class CeleryTaskStatus(BaseModel):
    id: str
    name: str
    status: TaskStatus
    start_time: datetime | None
    register_time: datetime | None


class FailedConnectorIndexingStatus(BaseModel):
    """Simplified version of ConnectorIndexingStatus for failed indexing attempts"""

    cc_pair_id: int
    name: str
    error_msg: str | None
    is_deletable: bool
    connector_id: int
    credential_id: int


class ConnectorStatus(BaseModel):
    """
    Represents the status of a connector,
    including indexing status elated information
    """

    cc_pair_id: int
    name: str
    connector: ConnectorSnapshot
    credential: CredentialSnapshot
    access_type: AccessType
    groups: list[int]


class ConnectorIndexingStatus(ConnectorStatus):
    """Represents the full indexing status of a connector"""

    cc_pair_status: ConnectorCredentialPairStatus
    # this is separate from the `status` above, since a connector can be `INITIAL_INDEXING`, `ACTIVE`,
    # or `PAUSED` and still be in a repeated error state.
    in_repeated_error_state: bool
    owner: str
    last_finished_status: IndexingStatus | None
    last_status: IndexingStatus | None
    last_success: datetime | None
    latest_index_attempt: IndexAttemptSnapshot | None
    docs_indexed: int
    in_progress: bool


class DocsCountOperator(str, Enum):
    GREATER_THAN = ">"
    LESS_THAN = "<"
    EQUAL_TO = "="


class ConnectorIndexingStatusLite(BaseModel):
    cc_pair_id: int
    name: str
    source: DocumentSource
    access_type: AccessType
    cc_pair_status: ConnectorCredentialPairStatus
    in_progress: bool
    in_repeated_error_state: bool
    last_finished_status: IndexingStatus | None
    last_status: IndexingStatus | None
    last_success: datetime | None
    # True when the caller may operate the pair (the OPERATE access level)
    is_editable: bool
    # per-action affordance map for the requesting user, from the same access
    # decisions the write guards enforce
    permissions: dict[str, bool]
    docs_indexed: int
    latest_index_attempt_docs_indexed: int | None


class SourceSummary(BaseModel):
    total_connectors: int
    active_connectors: int
    public_connectors: int
    total_docs_indexed: int


class ConnectorIndexingStatusLiteResponse(BaseModel):
    source: DocumentSource
    summary: SourceSummary
    current_page: int
    total_pages: int
    indexing_statuses: Sequence[ConnectorIndexingStatusLite | FederatedConnectorStatus]


class ConnectorCredentialPairIdentifier(BaseModel):
    connector_id: int
    credential_id: int


class CCPairManageAccessEntry(BaseModel):
    group_id: int
    role: ConnectorManageRole


def _require_unique_groups(
    entries: list[CCPairManageAccessEntry],
) -> list[CCPairManageAccessEntry]:
    if len({entry.group_id for entry in entries}) != len(entries):
        raise ValueError("Each group may appear only once in manage_access")
    return entries


# A group listed twice is rejected rather than resolved to one of its roles.
ManageAccessList = Annotated[
    list[CCPairManageAccessEntry], AfterValidator(_require_unique_groups)
]


def manage_access_by_group(
    entries: ManageAccessList,
) -> dict[int, ConnectorManageRole]:
    return {entry.group_id: entry.role for entry in entries}


NAMES_A_CREDENTIAL = "Give credential_id, credential_json or both."


def names_a_credential(
    credential_id: int | None, credential_json: dict[str, Any] | None
) -> bool:
    """A connector form's request names a saved credential or draft, a new
    account's values, or both (see onyx/server/documents/draft_credentials.py)."""
    return credential_id is not None or credential_json is not None


class CredentialSharing(BaseModel):
    """Who may reuse a credential: ``CredentialBase``'s sharing fields.

    ``admin_public`` shares with every admin (global MANAGE_CONNECTORS).
    ``groups`` (EE) shares with the users who hold Manage Connectors in one of
    the groups: its managers, and members who hold the permission globally.
    ``curator_public`` is kept for older clients and grants nothing."""

    admin_public: bool = True
    curator_public: bool = False
    groups: list[int] = Field(default_factory=list)
    name: str | None = None


class ConnectorCredentialPairMetadata(BaseModel):
    name: str
    access_type: AccessType
    auto_sync_options: dict[str, Any] | None = None
    # Groups that manage the pair as Editors, for clients that predate
    # manage_access. At most one of groups and manage_access may be set.
    groups: list[int] = Field(default_factory=list)
    # Groups that manage the pair, with their roles.
    manage_access: ManageAccessList = Field(default_factory=list)
    # Groups whose members may read a PRIVATE pair's documents. None means
    # the manage groups.
    data_access: list[int] | None = None
    processing_mode: ProcessingMode = ProcessingMode.REGULAR

    @model_validator(mode="after")
    def _one_manage_field(self) -> Self:
        if self.groups and self.manage_access:
            raise ValueError("Set groups or manage_access, not both")
        return self

    def manage_roles_by_group(self) -> dict[int, ConnectorManageRole]:
        if self.manage_access:
            return manage_access_by_group(self.manage_access)
        return dict.fromkeys(self.groups, ConnectorManageRole.EDITOR)


class ConnectorWithCredentialCreateRequest(BaseModel):
    """Creates a connector and pairs it with a credential in one request: a
    saved credential, or a new account that this request saves (see
    onyx/server/documents/draft_credentials.py)."""

    connector: ConnectorUpdateRequest
    pairing: ConnectorCredentialPairMetadata
    # A saved credential or the user's draft, a new account's values, or a
    # draft with its changed values.
    credential_id: int | None = None
    credential_json: dict[str, Any] | None = None
    # How a new account (a draft) is shared once saved. Rejected for a saved
    # credential.
    credential_sharing: CredentialSharing | None = None

    @model_validator(mode="after")
    def _names_a_credential(self) -> Self:
        if not names_a_credential(self.credential_id, self.credential_json):
            raise ValueError(NAMES_A_CREDENTIAL)
        return self


class CCStatusUpdateRequest(BaseModel):
    status: ConnectorCredentialPairStatus


class ConnectorCredentialPairDescriptor(BaseModel):
    id: int
    name: str
    connector: ConnectorSnapshot
    credential: CredentialSnapshot
    access_type: AccessType


class CCPairSummary(BaseModel):
    """Simplified connector-credential pair information with just essential data"""

    id: int
    name: str
    source: DocumentSource
    access_type: AccessType

    @classmethod
    def from_cc_pair_descriptor(
        cls, descriptor: ConnectorCredentialPairDescriptor
    ) -> "CCPairSummary":
        return cls(
            id=descriptor.id,
            name=descriptor.name,
            source=descriptor.connector.source,
            access_type=descriptor.access_type,
        )


class RunConnectorRequest(BaseModel):
    connector_id: int
    credential_ids: list[int] | None = None
    from_beginning: bool = False


class ConnectorRequestSubmission(BaseModel):
    connector_name: str


class CCPropertyUpdateRequest(BaseModel):
    name: str
    value: str


"""Connectors Models"""


class GoogleAppWebCredentials(BaseModel):
    client_id: str
    project_id: str
    auth_uri: str
    token_uri: str
    auth_provider_x509_cert_url: str
    client_secret: str
    redirect_uris: list[str]
    javascript_origins: list[str]


class GoogleAppCredentials(BaseModel):
    web: GoogleAppWebCredentials


class GoogleServiceAccountKey(BaseModel):
    type: str
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    auth_uri: str
    token_uri: str
    auth_provider_x509_cert_url: str
    client_x509_cert_url: str
    universe_domain: str


class GoogleServiceAccountCredentialRequest(BaseModel):
    google_primary_admin: str | None = None  # email of user to impersonate
    service_account_key: GoogleServiceAccountKey


class FileUploadResponse(BaseModel):
    file_paths: list[str]
    file_names: list[str]
    zip_metadata_file_id: str | None  # File ID pointing to metadata in file store


class ConnectorFileInfo(BaseModel):
    file_id: str
    file_name: str
    file_size: int | None = None
    upload_date: str | None = None


class ConnectorFilesResponse(BaseModel):
    files: list[ConnectorFileInfo]
    # Every file of the connector, not just the ones in `files`.
    total_items: int


class ObjectCreationIdResponse(BaseModel):
    id: int
    credential: CredentialSnapshot | None = None


class AuthStatus(BaseModel):
    authenticated: bool


class ConnectorGroupRestrictionsStatus(BaseModel):
    enabled: bool


class AuthUrl(BaseModel):
    auth_url: str


class GmailCallback(BaseModel):
    state: str
    code: str


class GDriveCallback(BaseModel):
    state: str
    code: str


class IndexingStatusRequest(BaseModel):
    secondary_index: bool = False
    source: DocumentSource | None = None
    access_type_filters: list[AccessType] = Field(default_factory=list)
    last_status_filters: list[IndexingStatus] = Field(default_factory=list)
    docs_count_operator: DocsCountOperator | None = None
    docs_count_value: int | None = None
    name_filter: str | None = None
    source_to_page: dict[DocumentSource, int] = Field(default_factory=dict)
    get_all_connectors: bool = False
