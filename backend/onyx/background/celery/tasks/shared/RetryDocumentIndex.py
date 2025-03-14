import httpx
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_delay
from tenacity import wait_random_exponential

from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields


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
    def delete_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
    ) -> int:
        return self.index.delete_single(
            doc_id,
            tenant_id=tenant_id,
            chunk_count=chunk_count,
        )

    @retry(
        retry=retry_if_exception_type(httpx.ReadTimeout),
        wait=wait_random_exponential(multiplier=1, max=MAX_WAIT),
        stop=stop_after_delay(STOP_AFTER),
    )
    def update_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> int:
        return self.index.update_single(
            doc_id,
            tenant_id=tenant_id,
            chunk_count=chunk_count,
            fields=fields,
            user_fields=user_fields,
        )
