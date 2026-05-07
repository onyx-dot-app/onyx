"""Per-cc-pair fetch + index for the targeted-reindex flow.

The targeted-reindex celery task delegates the actual connector
invocation + pipeline plumbing to this module so the task body stays
focused on lifecycle and resolution-tracking. One call to
`process_targets_for_cc_pair` covers a single cc_pair: it instantiates
the connector, converts the per-doc target rows into
`ConnectorFailure` inputs that the `Resolver.reindex` interface
expects, and streams yielded `Document` objects through the standard
indexing pipeline once per active search_settings (so PRESENT and
FUTURE indexes both receive the reindex during a model swap).

Connectors that don't subclass `Resolver` short-circuit: their targets
are reported as still-failing so the admin sees clearly that targeted
reindex isn't supported yet for that source.
"""

from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Sequence

from more_itertools import chunked
from sqlalchemy.orm import Session

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import Resolver
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.enums import AccessType
from onyx.db.models import IndexAttempt
from onyx.db.models import TargetedReindexJobTarget
from onyx.db.targeted_reindex import targets_to_connector_failures
from onyx.document_index.factory import get_all_document_indices
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.utils.logger import setup_logger
from onyx.utils.middleware import make_randomized_onyx_request_id

logger = setup_logger()


class CCPairReindexResult:
    """Per-cc-pair outcome.

    `landed_doc_ids` are the doc_ids that successfully made it through
    the pipeline. The task's resolution-tracking step only marks an
    `IndexAttemptError` resolved if the corresponding target's doc is
    in this set.

    `failed_doc_ids` covers connector-side failures (connector yielded
    `ConnectorFailure`) plus pipeline-side failures (handler caught an
    exception during chunk/embed/write). They drive the per-job
    `still_failing_count`.

    `unsupported` is True iff the connector class does not implement
    `Resolver`. All targets for that cc_pair are bucketed into
    `failed_doc_ids` in that case so the admin sees a clear signal.
    """

    def __init__(
        self,
        landed_doc_ids: set[str],
        failed_doc_ids: set[str],
        unsupported: bool,
    ) -> None:
        self.landed_doc_ids = landed_doc_ids
        self.failed_doc_ids = failed_doc_ids
        self.unsupported = unsupported


def _flush_batch(
    *,
    documents: list[Document],
    attempt: IndexAttempt,
    tenant_id: str,
    db_session: Session,
    batch_num: int,
) -> tuple[set[str], set[str]]:
    """Run a single `Document` batch through the indexing pipeline for
    one synthetic IndexAttempt's search_settings.

    `batch_num` is the 0-indexed position of this batch within the
    attempt's overall reindex run; it propagates into tracing /
    `IndexAttemptMetadata.structured_id` so each batch is
    distinguishable in logs and sentry breadcrumbs.

    Returns `(landed_doc_ids, failed_doc_ids)`. The pipeline's adapter
    already wraps writes in `prepare_to_modify_documents`, so concurrent
    full-crawl writes on the same docs are safely serialized.
    """
    if not documents:
        return set(), set()

    search_settings = attempt.search_settings
    if search_settings is None:
        # Synthetic attempt should always have search_settings linked; if
        # the row is missing, treat all docs as failed for this attempt
        # rather than crash the whole job.
        logger.warning(
            "synthetic IndexAttempt id=%s missing search_settings; "
            "skipping pipeline run",
            attempt.id,
        )
        return set(), {d.id for d in documents}

    embedder = DefaultIndexingEmbedder.from_db_search_settings(
        search_settings=search_settings,
        callback=None,
    )
    document_indices = get_all_document_indices(
        search_settings,
        None,
        httpx_client=HttpxPool.get("vespa"),
    )
    metadata = IndexAttemptMetadata(
        attempt_id=attempt.id,
        connector_id=attempt.connector_credential_pair.connector.id,
        credential_id=attempt.connector_credential_pair.credential.id,
        request_id=make_randomized_onyx_request_id("TRX"),
        structured_id="%s:%s:%s:targeted:%s"
        % (tenant_id, attempt.connector_credential_pair_id, attempt.id, batch_num),
        batch_num=batch_num,
    )
    adapter = DocumentIndexingBatchAdapter(
        db_session=db_session,
        connector_id=attempt.connector_credential_pair.connector.id,
        credential_id=attempt.connector_credential_pair.credential.id,
        tenant_id=tenant_id,
        index_attempt_metadata=metadata,
    )

    result = run_indexing_pipeline(
        embedder=embedder,
        document_indices=document_indices,
        ignore_time_skip=True,
        db_session=db_session,
        tenant_id=tenant_id,
        document_batch=documents,
        request_id=metadata.request_id,
        adapter=adapter,
    )

    failed_ids: set[str] = set()
    for f in result.failures or []:
        if f.failed_document is not None:
            failed_ids.add(f.failed_document.document_id)

    landed_ids = {d.id for d in documents} - failed_ids
    return landed_ids, failed_ids


def process_targets_for_cc_pair(
    *,
    cc_pair_id: int,
    targets: Sequence[TargetedReindexJobTarget],
    attempts: Iterable[IndexAttempt],
    tenant_id: str,
    db_session: Session,
) -> CCPairReindexResult:
    """Fetch + index every target for one cc_pair.

    `attempts` is the set of synthetic IndexAttempts the create step
    spawned for this cc_pair (one per active search_settings). The
    connector is instantiated once and its `reindex` output is fed
    into the pipeline once per attempt so all active indexes receive
    the same Documents.
    """
    target_doc_ids = {t.document_id for t in targets}
    cc_pair_attempts = [
        a for a in attempts if a.connector_credential_pair_id == cc_pair_id
    ]
    if not cc_pair_attempts:
        # Shouldn't happen — create_targeted_reindex_job spawns one
        # synthetic attempt per active search_settings — but be
        # defensive so we don't crash the whole job.
        logger.warning(
            "no synthetic IndexAttempt for cc_pair_id=%s; skipping", cc_pair_id
        )
        return CCPairReindexResult(set(), target_doc_ids, unsupported=False)

    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session, cc_pair_id=cc_pair_id
    )
    if cc_pair is None:
        logger.warning(
            "cc_pair_id=%s no longer exists; marking targets still_failing",
            cc_pair_id,
        )
        return CCPairReindexResult(set(), target_doc_ids, unsupported=False)

    connector = instantiate_connector(
        db_session=db_session,
        source=cc_pair.connector.source,
        input_type=cc_pair.connector.input_type,
        connector_specific_config=cc_pair.connector.connector_specific_config,
        credential=cc_pair.credential,
    )
    if not isinstance(connector, Resolver):
        logger.info(
            "connector source=%s does not implement Resolver; targets "
            "marked still_failing",
            cc_pair.connector.source,
        )
        return CCPairReindexResult(set(), target_doc_ids, unsupported=True)

    include_permissions = cc_pair.access_type == AccessType.SYNC
    failures = targets_to_connector_failures(targets, db_session)

    # Materialize the connector output once. MAX_TARGETS_PER_REQUEST caps
    # the universe at 100 docs total per job, so this is bounded.
    docs: list[Document] = []
    failed_from_connector: set[str] = set()
    for item in connector.reindex(
        errors=failures, include_permissions=include_permissions
    ):
        if isinstance(item, ConnectorFailure):
            if item.failed_document is not None:
                failed_from_connector.add(item.failed_document.document_id)
            continue
        if isinstance(item, Document):
            docs.append(item)
            continue
        # TODO(targeted-reindex follow-up): plumb HierarchyNode yields
        # through the same path the indexing pipeline uses for full
        # crawls. Skipping is safe today (a missing ancestor folder
        # node falls back to "source-type root" in KG selection), but
        # for cases like "admin restored a folder's permissions and
        # reindexed its docs" the new ancestor relationship would
        # otherwise stay missing until the next full crawl.

    # Per-attempt pipeline run. Each attempt commits to its own
    # search_settings's document_indices.
    landed_overall: set[str] = set()
    failed_pipeline_overall: set[str] = set()
    for attempt in cc_pair_attempts:
        for batch_num, batch in enumerate(chunked(docs, INDEX_BATCH_SIZE)):
            landed, failed = _flush_batch(
                documents=list(batch),
                attempt=attempt,
                tenant_id=tenant_id,
                db_session=db_session,
                batch_num=batch_num,
            )
            landed_overall |= landed
            failed_pipeline_overall |= failed

    # Conservative landing: a doc is only "landed" if some attempt
    # accepted it AND no attempt or upstream phase failed it. The set
    # math is (landed_overall - failed_*), which means if PRESENT
    # accepts doc X but FUTURE fails it during a model swap, doc X is
    # NOT counted as landed and its source error stays open. This is
    # the right call for resolution tracking — partial dual-index
    # landing should not auto-resolve the failure. If the strictness
    # ever causes too many false-still-failing on transient infra
    # blips, switch to per-attempt landing tracking and require all
    # attempts to land independently.
    docs_never_yielded = target_doc_ids - {d.id for d in docs} - failed_from_connector
    failed_doc_ids = (
        failed_from_connector | failed_pipeline_overall | docs_never_yielded
    )
    landed_doc_ids = landed_overall - failed_doc_ids

    return CCPairReindexResult(
        landed_doc_ids=landed_doc_ids,
        failed_doc_ids=failed_doc_ids,
        unsupported=False,
    )


def group_targets_by_cc_pair(
    targets: Sequence[TargetedReindexJobTarget],
) -> dict[int, list[TargetedReindexJobTarget]]:
    by_cc_pair: dict[int, list[TargetedReindexJobTarget]] = defaultdict(list)
    for t in targets:
        by_cc_pair[t.cc_pair_id].append(t)
    return by_cc_pair
