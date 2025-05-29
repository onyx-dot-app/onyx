from pydantic import BaseModel
from retry import retry
from sqlalchemy import or_

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntity
from onyx.db.models import KGRelationship
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


def update_kg_chunks_vespa_info_for_entity(
    entity: KGEntity,
    index_name: str,
    tenant_id: str,
) -> None:
    """Add the entity information to vespa for filtered search."""
    if entity.document_id is None:
        raise ValueError("Entity has no document_id")

    # Add entity, and the generalized entity
    kg_entities = {entity.id_name, f"{entity.entity_type_id_name}::*"}

    # Add relationship and the generalized relationships in case
    # an entity referenced already by a relationship gains a document_id
    kg_relationships: set[str] = set()
    with get_session_with_current_tenant() as db_session:
        relationships = (
            db_session.query(KGRelationship)
            .filter(
                or_(
                    KGRelationship.source_node == entity.id_name,
                    KGRelationship.target_node == entity.id_name,
                )
            )
            .all()
        )
        for relationship in relationships:
            kg_relationships.update(
                {
                    relationship.id_name,
                    f"{relationship.source_node_type}::*__{relationship.type}__{relationship.target_node}",
                    f"{relationship.source_node}__{relationship.type}__{relationship.target_node_type}::*",
                    f"{relationship.source_node_type}::*__{relationship.type}__{relationship.target_node_type}::*",
                }
            )

    # get chunks in the entity document
    chunks = _get_chunks_via_visit_api(
        chunk_request=VespaChunkRequest(document_id=entity.document_id),
        index_name=index_name,
        filters=IndexFilters(access_control_list=None),
        field_names=["chunk_id", "metadata"],
        get_large_chunks=False,
    )

    # update vespa
    kg_update_requests = [
        KGUChunkUpdateRequest(
            document_id=entity.document_id,
            chunk_id=chunk["fields"]["chunk_id"],
            core_entity=entity.id_name,
            entities=kg_entities,
            relationships=kg_relationships or None,
        )
        for chunk in chunks
    ]
    update_kg_chunks_vespa_info(
        kg_update_requests=kg_update_requests,
        index_name=index_name,
        tenant_id=tenant_id,
    )


def update_kg_chunks_vespa_info_for_relationship(
    relationship: KGRelationship,
    index_name: str,
    tenant_id: str,
) -> None:
    """Add the relationship information to vespa for filtered search."""
    # Add relationship, and the generalized relationship
    kg_relationships = {
        relationship.id_name,
        f"{relationship.source_node_type}::*__{relationship.type}__{relationship.target_node}",
        f"{relationship.source_node}__{relationship.type}__{relationship.target_node_type}::*",
        f"{relationship.source_node_type}::*__{relationship.type}__{relationship.target_node_type}::*",
    }

    for entity_id_name in [relationship.source_node, relationship.target_node]:
        with get_session_with_current_tenant() as db_session:
            source_document_id: str | None = (
                db_session.query(KGEntity.document_id)
                .filter(KGEntity.id_name == entity_id_name)
                .scalar()
            )
            if source_document_id is None:
                continue

        # get chunks in the entity document
        chunks = _get_chunks_via_visit_api(
            chunk_request=VespaChunkRequest(document_id=source_document_id),
            index_name=index_name,
            filters=IndexFilters(access_control_list=None),
            field_names=["chunk_id"],
            get_large_chunks=False,
        )

        # update vespa
        kg_update_requests = [
            KGUChunkUpdateRequest(
                document_id=source_document_id,
                chunk_id=chunk["fields"]["chunk_id"],
                core_entity=entity_id_name,
                relationships=kg_relationships,
            )
            for chunk in chunks
        ]
        update_kg_chunks_vespa_info(
            kg_update_requests=kg_update_requests,
            index_name=index_name,
            tenant_id=tenant_id,
        )
