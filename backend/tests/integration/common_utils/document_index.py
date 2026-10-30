from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from onyx.configs.app_configs import (
    OPENSEARCH_ADMIN_PASSWORD,
    OPENSEARCH_ADMIN_USERNAME,
    OPENSEARCH_HOST,
    OPENSEARCH_REST_API_PORT,
    OPENSEARCH_USE_SSL,
)
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.opensearch.cc_pair_ids_backfill import (
    load_cc_pair_ids_backfill_progress,
    store_cc_pair_ids_backfill_progress,
)
from onyx.redis.redis_pool import get_redis_client

_BACKFILL_LOCK_TIMEOUT_S = 60 * 5


def mark_cc_pair_ids_backfill_complete() -> None:
    """Marks the cc_pair_ids backfill of the current index as complete. A reset
    wipes its progress, and the beat task can take minutes to finish it. Holds
    the backfill's lock, so a running backfill cannot overwrite the result."""
    lock = get_redis_client().lock(
        OnyxRedisLocks.CC_PAIR_IDS_BACKFILL_LOCK, timeout=_BACKFILL_LOCK_TIMEOUT_S
    )
    # A backfill run holds the lock for at most its time budget.
    if not lock.acquire(blocking=True, blocking_timeout=_BACKFILL_LOCK_TIMEOUT_S):
        raise TimeoutError("The cc_pair_ids backfill lock was not released")
    try:
        with get_session_with_current_tenant() as db_session:
            progress = load_cc_pair_ids_backfill_progress(
                get_current_search_settings(db_session)
            )
        progress.pending_cc_pair_ids = []
        progress.last_document_id = None
        store_cc_pair_ids_backfill_progress(progress)
    finally:
        if lock.owned():
            lock.release()


class DocumentIndexClient:
    """Test client for inspecting the chunks stored in the document index.

    The current index name is resolved lazily on each call rather than at
    construction time. The docprocessing worker performs an in-flight swap from
    ``danswer_chunk`` to ``danswer_chunk_<model>`` the first time it indexes
    after a Postgres reset; resolving the name eagerly would cache the pre-swap
    value and query a non-existent index.
    """

    def __init__(self) -> None:
        self._client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_REST_API_PORT}],
            http_auth=(OPENSEARCH_ADMIN_USERNAME, OPENSEARCH_ADMIN_PASSWORD),
            use_ssl=OPENSEARCH_USE_SSL,
            verify_certs=False,
            ssl_show_warn=False,
        )

    @property
    def index_name(self) -> str:
        with get_session_with_current_tenant() as db_session:
            return get_current_search_settings(db_session).index_name

    def get_chunks_by_document_id(
        self, document_ids: list[str], wanted_chunk_count: int = 1_000
    ) -> list[dict[str, Any]]:
        """Returns the stored fields (``_source``) of every chunk that belongs
        to one of the given documents."""
        index_name = self.index_name
        # Refresh first so chunks indexed just before the call are visible.
        try:
            self._client.indices.refresh(index=index_name)
        except NotFoundError:
            return []

        body: dict[str, Any] = {
            "size": wanted_chunk_count,
            "query": {"terms": {"document_id": document_ids}},
        }
        try:
            result = self._client.search(index=index_name, body=body)
        except NotFoundError:
            return []

        hits = result.get("hits", {}).get("hits", [])
        return [dict(hit.get("_source", {})) for hit in hits]
