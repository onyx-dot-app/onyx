import httpx
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_delay
from tenacity import wait_random_exponential

from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import MetadataUpdateRequest


class RetryDocumentIndex:
    """A wrapper class to help with specific retries against Vespa involving
    read timeouts.

    wait_random_exponential implements full jitter as per this article:
    https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/"""

    MAX_WAIT = 30

    # STOP_AFTER + MAX_WAIT should be slightly less (5?) than the celery soft_time_limit
    STOP_AFTER = 70

    def __init__(self, index: DocumentIndex):
        self.index: DocumentIndex = index

    @retry(
        retry=retry_if_exception_type(httpx.ReadTimeout),
        wait=wait_random_exponential(multiplier=1, max=MAX_WAIT),
        stop=stop_after_delay(STOP_AFTER),
    )
    def delete(
        self,
        doc_id: str,
        chunk_count: int | None = None,
    ) -> int:
        return self.index.delete(doc_id, chunk_count=chunk_count)

    @retry(
        retry=retry_if_exception_type(httpx.ReadTimeout),
        wait=wait_random_exponential(multiplier=1, max=MAX_WAIT),
        stop=stop_after_delay(STOP_AFTER),
    )
    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
    ) -> None:
        self.index.update(update_requests)
