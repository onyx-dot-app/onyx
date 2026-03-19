import time
from collections import defaultdict
from http import HTTPStatus

import httpx

from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import DocumentFailure
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentInsertionRecord
from onyx.document_index.interfaces import IndexBatchParams
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _log_insufficient_storage_error(e: Exception) -> None:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == HTTPStatus.INSUFFICIENT_STORAGE:
            logger.error(
                "NOTE: HTTP Status 507 Insufficient Storage indicates "
                "you need to allocate more memory or disk space to the "
                "Vespa/index container."
            )


def write_chunks_to_vector_db_with_backoff(
    document_index: DocumentIndex,
    chunks: list[DocMetadataAwareIndexChunk],
    index_batch_params: IndexBatchParams,
) -> tuple[list[DocumentInsertionRecord], list[ConnectorFailure]]:
    """Tries to insert all chunks in one large batch. If that batch fails for any reason,
    goes document by document to isolate the failure(s).

    IMPORTANT: must pass in whole documents at a time not individual chunks, since the
    vector DB interface assumes that all chunks for a single document are present.
    """

    # first try to write the chunks to the vector db
    try:
        return (
            list(
                document_index.index(
                    chunks=chunks,
                    index_batch_params=index_batch_params,
                )
            ),
            [],
        )
    except Exception as e:
        logger.exception(
            "Failed to write chunk batch to vector db. Trying individual docs."
        )

        # give some specific logging on this common failure case.
        _log_insufficient_storage_error(e)

        # wait a couple seconds just to give the vector db a chance to recover
        time.sleep(2)

    # try writing each doc one by one
    chunks_for_docs: dict[str, list[DocMetadataAwareIndexChunk]] = defaultdict(list)
    for chunk in chunks:
        chunks_for_docs[chunk.source_document.id].append(chunk)

    insertion_records: list[DocumentInsertionRecord] = []
    failures: list[ConnectorFailure] = []
    for doc_id, chunks_for_doc in chunks_for_docs.items():
        try:
            insertion_records.extend(
                document_index.index(
                    chunks=chunks_for_doc,
                    index_batch_params=index_batch_params,
                )
            )
        except Exception as e:
            logger.exception(
                f"Failed to write document chunks for '{doc_id}' to vector db"
            )

            # give some specific logging on this common failure case.
            _log_insufficient_storage_error(e)

            failures.append(
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=doc_id,
                        document_link=(
                            chunks_for_doc[0].get_link() if chunks_for_doc else None
                        ),
                    ),
                    failure_message=str(e),
                    exception=e,
                )
            )

    return insertion_records, failures
