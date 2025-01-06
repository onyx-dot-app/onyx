import concurrent.futures
from uuid import UUID

import httpx
from retry import retry

from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import NUM_THREADS
from onyx.utils.logger import setup_logger

logger = setup_logger()


CONTENT_SUMMARY = "content_summary"


@retry(tries=10, delay=1, backoff=2)
def _retryable_http_delete(http_client: httpx.Client, url: str) -> None:
    res = http_client.delete(url)
    res.raise_for_status()


def _delete_vespa_chunk(
    doc_chunk_id: UUID, index_name: str, http_client: httpx.Client
) -> None:
    try:
        _retryable_http_delete(
            http_client,
            f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{doc_chunk_id}",
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to delete chunk, details: {e.response.text}")
        raise


def delete_vespa_chunks(
    doc_chunk_ids: list[UUID],
    index_name: str,
    http_client: httpx.Client,
    executor: concurrent.futures.ThreadPoolExecutor | None = None,
) -> None:
    external_executor = True

    if not executor:
        external_executor = False
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS)

    try:
        chunk_deletion_future = {
            executor.submit(
                _delete_vespa_chunk, doc_chunk_id, index_name, http_client
            ): doc_chunk_id
            for doc_chunk_id in doc_chunk_ids
        }
        for future in concurrent.futures.as_completed(chunk_deletion_future):
            # Will raise exception if the deletion raised an exception
            future.result()

    finally:
        if not external_executor:
            executor.shutdown(wait=True)
