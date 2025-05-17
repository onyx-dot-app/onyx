from pydantic import BaseModel
from retry import retry

from onyx.document_index.vespa.chunk_retrieval import _get_chunks_via_visit_api
from onyx.document_index.vespa.chunk_retrieval import VespaChunkRequest
from onyx.document_index.vespa.index import IndexFilters
from onyx.document_index.vespa.index import KGUChunkUpdateRequest
from onyx.document_index.vespa.index import VespaIndex
from onyx.utils.logger import setup_logger

# from backend.onyx.chat.process_message import get_inference_chunks
# from backend.onyx.document_index.vespa.index import VespaIndex

logger = setup_logger()


class KGChunkInfo(BaseModel):
    kg_relationships: dict[str, int]
    kg_entities: dict[str, int]
    kg_terms: dict[str, int]


@retry(tries=3, delay=1, backoff=2)
def get_document_kg_info(
    document_id: str,
    index_name: str,
    filters: IndexFilters | None = None,
) -> dict | None:
    """
    Retrieve the kg_info attribute from a Vespa document by its document_id.
    Args:
        document_id: The unique identifier of the document.
        index_name: The name of the Vespa index to query.
        filters: Optional access control filters to apply.
    Returns:
        The kg_info dictionary if found, None otherwise.
    """
    # Use the existing visit API infrastructure
    kg_doc_info: dict[int, KGChunkInfo] = {}

    document_chunks = _get_chunks_via_visit_api(
        chunk_request=VespaChunkRequest(document_id=document_id),
        index_name=index_name,
        filters=filters or IndexFilters(access_control_list=None),
        field_names=["kg_relationships", "kg_entities", "kg_terms"],
        get_large_chunks=False,
    )

    for chunk_id, document_chunk in enumerate(document_chunks):
        kg_chunk_info = KGChunkInfo(
            kg_relationships=document_chunk["fields"].get("kg_relationships", {}),
            kg_entities=document_chunk["fields"].get("kg_entities", {}),
            kg_terms=document_chunk["fields"].get("kg_terms", {}),
        )

        kg_doc_info[chunk_id] = kg_chunk_info  # TODO: check the chunk id is correct!

    return kg_doc_info


@retry(tries=3, delay=1, backoff=2)
def update_kg_chunks_vespa_info(
    kg_update_requests: list[KGUChunkUpdateRequest],
    index_name: str,
    tenant_id: str,
) -> None:
    """ """
    # Use the existing visit API infrastructure
    vespa_index = VespaIndex(
        index_name=index_name,
        secondary_index_name=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=False,
        multitenant=False,
        httpx_client=None,
    )

    vespa_index.kg_chunk_updates(
        kg_update_requests=kg_update_requests, tenant_id=tenant_id
    )
