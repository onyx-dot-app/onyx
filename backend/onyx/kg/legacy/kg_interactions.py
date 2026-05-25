from onyx.db.document import get_document_kg_entities_and_relationships
from onyx.db.document import get_num_chunks_for_document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.vespa.vespa_document_index import KGUChunkUpdateRequest
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def update_kg_chunks_vespa_info(
    kg_update_requests: list[KGUChunkUpdateRequest],
    index_name: str,
    tenant_id: str,
) -> None:
    """ """
    vespa_index = VespaDocumentIndex(
        index_name=index_name,
        tenant_state=TenantState(tenant_id=tenant_id, multitenant=MULTI_TENANT),
        large_chunks_enabled=False,
        httpx_client=None,
    )

    vespa_index.kg_chunk_updates(
        kg_update_requests=kg_update_requests, tenant_id=tenant_id
    )


def get_kg_vespa_info_update_requests_for_document(
    document_id: str,
) -> list[KGUChunkUpdateRequest]:
    """Get the kg_info update requests for a document."""
    # get all entities and relationships tied to the document
    with get_session_with_current_tenant() as db_session:
        entities, relationships = get_document_kg_entities_and_relationships(
            db_session, document_id
        )

    # create the kg vespa info
    kg_entities = {entity.id_name for entity in entities}
    kg_relationships = {relationship.id_name for relationship in relationships}

    # get chunks in the document
    with get_session_with_current_tenant() as db_session:
        num_chunks = get_num_chunks_for_document(db_session, document_id)

    # get vespa update requests
    return [
        KGUChunkUpdateRequest(
            document_id=document_id,
            chunk_id=chunk_id,
            core_entity="unused",
            entities=kg_entities,
            relationships=kg_relationships or None,
        )
        for chunk_id in range(num_chunks)
    ]
