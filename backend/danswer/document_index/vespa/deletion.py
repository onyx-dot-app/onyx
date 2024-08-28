import concurrent.futures

import httpx
from retry import retry

from danswer.document_index.vespa.chunk_retrieval import (
    get_all_vespa_ids_for_document_id,
)
from danswer.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from danswer.document_index.vespa_constants import NUM_THREADS
from danswer.utils.logger import setup_logger

logger = setup_logger()


CONTENT_SUMMARY = "content_summary"


@retry(tries=3, delay=1, backoff=2)
def _delete_vespa_doc_chunks(
    document_id: str, index_name: str, http_client: httpx.Client
) -> None:
    doc_chunk_ids = get_all_vespa_ids_for_document_id(
        document_id=document_id,
        index_name=index_name,
        get_large_chunks=True,
    )

    for chunk_id in doc_chunk_ids:
        try:
            res = http_client.delete(
                f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{chunk_id}"
            )
            res.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to delete chunk, details: {e.response.text}")
            raise


def delete_vespa_docs(
    document_ids: list[str],
    index_name: str,
    http_client: httpx.Client,
    executor: concurrent.futures.ThreadPoolExecutor | None = None,
) -> None:
    external_executor = True

    if not executor:
        external_executor = False
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS)

    try:
        doc_deletion_future = {
            executor.submit(
                _delete_vespa_doc_chunks, doc_id, index_name, http_client
            ): doc_id
            for doc_id in document_ids
        }
        for future in concurrent.futures.as_completed(doc_deletion_future):
            # Will raise exception if the deletion raised an exception
            future.result()

    finally:
        if not external_executor:
            executor.shutdown(wait=True)
