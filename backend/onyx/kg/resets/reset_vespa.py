from collections.abc import Callable

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import Document
from onyx.document_index.document_index_utils import get_uuid_from_chunk_info
from onyx.document_index.vespa.chunk_retrieval import _get_chunks_via_visit_api
from onyx.document_index.vespa.chunk_retrieval import VespaChunkRequest
from onyx.document_index.vespa.index import IndexFilters
from onyx.document_index.vespa.index import KGVespaChunkUpdateRequest
from onyx.document_index.vespa.index import VespaIndex
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def reset_vespa_kg_index(tenant_id: str, index_name: str) -> None:
    logger.info(f"Resetting kg vespa index {index_name} for tenant {tenant_id}")
    vespa_index = VespaIndex(
        index_name=index_name,
        secondary_index_name=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=False,
        multitenant=False,
        httpx_client=None,
    )

    # Prepare the update request to remove fields
    reset_update_dict = {
        "fields": {
            "kg_entities": {"assign": {}},
            "kg_relationships": {"assign": {}},
            "kg_terms": {"assign": {}},
        }
    }

    # Get all the documents that have kg processing
    with get_session_with_current_tenant() as db_session:
        documents = (
            db_session.query(Document).filter(Document.kg_stage.is_not(None)).all()
        )

    # Reset the kg fields in batches of 8 documents
    for idx in range(0, len(documents), 8):
        functions_with_args: list[tuple[Callable, tuple]] = [
            (
                _get_chunks_via_visit_api,
                (
                    VespaChunkRequest(document_id=document.id),
                    index_name,
                    IndexFilters(access_control_list=None),
                    ["document_id", "chunk_id"],
                    False,
                ),
            )
            for document in documents[idx : idx + 8]
        ]
        kg_batched_chunks: list[list[dict] | None] = run_functions_tuples_in_parallel(
            functions_with_args, allow_failures=True
        )

        # reset the kg fields for every chunk in each document
        for batch in kg_batched_chunks:
            if batch is None:
                continue

            vespa_requests: list[KGVespaChunkUpdateRequest] = []
            for chunk in batch:
                doc_chunk_id = get_uuid_from_chunk_info(
                    document_id=chunk["fields"]["document_id"],
                    chunk_id=chunk["fields"]["chunk_id"],
                    tenant_id=tenant_id,
                    large_chunk_id=None,
                )
                vespa_requests.append(
                    KGVespaChunkUpdateRequest(
                        document_id=chunk["fields"]["document_id"],
                        chunk_id=chunk["fields"]["chunk_id"],
                        url=f"{DOCUMENT_ID_ENDPOINT.format(index_name=vespa_index.index_name)}/{doc_chunk_id}",
                        update_request=reset_update_dict,
                    )
                )

            with vespa_index.httpx_client_context as httpx_client:
                vespa_index._apply_kg_chunk_updates_batched(
                    vespa_requests, httpx_client
                )
