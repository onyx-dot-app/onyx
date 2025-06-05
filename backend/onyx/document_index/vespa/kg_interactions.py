from pydantic import BaseModel
from retry import retry

from onyx.db.document import get_document_kg_entities_and_relationships
from onyx.db.engine import get_session_with_current_tenant
from onyx.document_index.vespa.chunk_retrieval import _get_chunks_via_visit_api
from onyx.document_index.vespa.chunk_retrieval import VespaChunkRequest
from onyx.document_index.vespa.index import IndexFilters
from onyx.document_index.vespa.index import KGUChunkUpdateRequest
from onyx.document_index.vespa.index import VespaIndex
from onyx.kg.utils.formatting_utils import generalize_entities
from onyx.kg.utils.formatting_utils import generalize_relationships
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

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
        multitenant=MULTI_TENANT,
        httpx_client=None,
    )

    vespa_index.kg_chunk_updates(
        kg_update_requests=kg_update_requests, tenant_id=tenant_id
    )


def get_kg_vespa_info_update_requests_for_document(
    document_id: str, index_name: str, tenant_id: str
) -> list[KGUChunkUpdateRequest]:
    """Get the kg_info update requests for a document."""
    # get all entities and relationships tied to the document
    with get_session_with_current_tenant() as db_session:
        entities, relationships = get_document_kg_entities_and_relationships(
            db_session, document_id
        )

    # create the kg vespa info
    entity_id_names = [entity.id_name for entity in entities]
    relationship_id_names = [relationship.id_name for relationship in relationships]

    kg_entities = generalize_entities(entity_id_names) | set(entity_id_names)
    kg_relationships = generalize_relationships(relationship_id_names) | set(
        relationship_id_names
    )

    # get chunks in the document
    chunks = _get_chunks_via_visit_api(
        chunk_request=VespaChunkRequest(document_id=document_id),
        index_name=index_name,
        filters=IndexFilters(access_control_list=None),
        field_names=["chunk_id"],
        get_large_chunks=False,
    )

    # get vespa update requests
    return [
        KGUChunkUpdateRequest(
            document_id=document_id,
            chunk_id=chunk["fields"]["chunk_id"],
            core_entity="unused",
            entities=kg_entities,
            relationships=kg_relationships or None,
        )
        for chunk in chunks
    ]
