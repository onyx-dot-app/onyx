"""OpenSearch-side primitive for reclaiming an old (PAST) index's data after a
reindex. Deployment-mode-aware and idempotent — safe to re-run until it reports
COMPLETE. Driven by the reclaim beat task (background/celery/tasks/index_reclaim).
"""

from enum import Enum

from onyx.configs.app_configs import OLD_INDEX_RECLAIM_DELETE_BATCH_SIZE
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ReclaimOutcome(str, Enum):
    # The index's data for this scope is fully gone; safe to finalize.
    COMPLETE = "complete"
    # Docs still remain (a delete timed out / partially failed); retry next tick.
    INCOMPLETE = "incomplete"


def reclaim_index_data(
    index_name: str, is_multi_tenant: bool, tenant_id: str
) -> ReclaimOutcome:
    """Delete an old index's data. Idempotent — safe to call repeatedly.

    Single-tenant: the physical index belongs to this deployment, so drop it whole in
    one metadata op. Multi-tenant: the index is SHARED across tenants (dropping it would
    wipe everyone), so delete this tenant's slice by query, capped at
    OLD_INDEX_RECLAIM_DELETE_BATCH_SIZE docs per call so a whale can't run past the
    client timeout. Verify by count: COMPLETE only once zero of the tenant's docs
    remain, else INCOMPLETE so the caller re-runs.
    """
    client = OpenSearchIndexClient(index_name=index_name)
    try:
        if not client.index_exists():
            logger.info("Old index %s already gone; nothing to reclaim.", index_name)
            return ReclaimOutcome.COMPLETE

        if not is_multi_tenant:
            existed = client.delete_index()
            logger.info(
                "Reclaimed old index %s (physical drop, existed=%s).",
                index_name,
                existed,
            )
            return ReclaimOutcome.COMPLETE

        tenant_query = {"query": {"term": {TENANT_ID_FIELD_NAME: {"value": tenant_id}}}}
        # Bounded per call (max_docs) so a whale tenant can't run past the client HTTP
        # timeout; the caller re-runs on INCOMPLETE. refresh=True so the count below
        # sees the deletions (else it reads stale and falsely reports INCOMPLETE).
        deleted = client.delete_by_query(
            tenant_query, refresh=True, max_docs=OLD_INDEX_RECLAIM_DELETE_BATCH_SIZE
        )
        remaining = client.count_by_query(tenant_query)
        logger.info(
            "Reclaimed tenant %s from shared index %s: deleted=%s remaining=%s.",
            tenant_id,
            index_name,
            deleted,
            remaining,
        )
        return ReclaimOutcome.COMPLETE if remaining == 0 else ReclaimOutcome.INCOMPLETE
    finally:
        client.close()
