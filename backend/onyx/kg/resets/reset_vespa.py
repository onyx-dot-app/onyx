from typing import Any

from retry import retry

from onyx.configs.constants import DocumentSource
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import Connector
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import KGEntityType
from onyx.document_index.document_index_utils import get_uuid_from_chunk_info
from onyx.document_index.vespa.chunk_retrieval import _get_chunks_via_visit_api
from onyx.document_index.vespa.chunk_retrieval import VespaChunkRequest
from onyx.document_index.vespa.index import IndexFilters
from onyx.document_index.vespa.index import KGVespaChunkUpdateRequest
from onyx.document_index.vespa.index import VespaIndex
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


@retry(tries=3, delay=1, backoff=2)
def _reset_vespa_for_doc(document_id: str, tenant_id: str, index_name: str) -> None:
    vespa_index = VespaIndex(
        index_name=index_name,
        secondary_index_name=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=False,
        multitenant=MULTI_TENANT,
        httpx_client=None,
    )

    reset_update_dict: dict[str, Any] = {
        "fields": {
            "kg_entities": {"assign": {}},
            "kg_relationships": {"assign": {}},
            "kg_terms": {"assign": {}},
        }
    }

    chunks = _get_chunks_via_visit_api(
        VespaChunkRequest(document_id=document_id),
        index_name,
        IndexFilters(access_control_list=None),
        ["chunk_id"],
        False,
    )

    vespa_requests: list[KGVespaChunkUpdateRequest] = []
    for chunk in chunks:
        doc_chunk_id = get_uuid_from_chunk_info(
            document_id=document_id,
            chunk_id=chunk["fields"]["chunk_id"],
            tenant_id=tenant_id,
            large_chunk_id=None,
        )
        vespa_requests.append(
            KGVespaChunkUpdateRequest(
                document_id=document_id,
                chunk_id=chunk["fields"]["chunk_id"],
                url=f"{DOCUMENT_ID_ENDPOINT.format(index_name=vespa_index.index_name)}/{doc_chunk_id}",
                update_request=reset_update_dict,
            )
        )

    with vespa_index.httpx_client_context as httpx_client:
        vespa_index._apply_kg_chunk_updates_batched(vespa_requests, httpx_client)


def reset_vespa_kg_index(
    tenant_id: str, index_name: str, source_name: str | None = None
) -> None:
    """
    Reset the kg info in vespa for all documents of a given source name,
    or all documents from kg grounded sources if source_name is None.
    """
    logger.info(
        f"Resetting kg vespa index {index_name} for tenant {tenant_id}, "
        f"source: {source_name if source_name else 'all'}"
    )

    # Get all documents that need a vespa reset
    with get_session_with_current_tenant() as db_session:
        if source_name:
            # get all connectors of the given source name
            kg_connectors = [
                connector.id
                for connector in db_session.query(Connector)
                .filter(Connector.source == DocumentSource(source_name))
                .all()
            ]
        else:
            # get all connectors that have kg enabled
            kg_sources = [
                DocumentSource(et.grounded_source_name)
                for et in db_session.query(KGEntityType)
                .filter(
                    KGEntityType.grounded_source_name.is_not(None),
                    KGEntityType.active.is_(True),
                )
                .distinct()
                .all()
            ]
            kg_connectors = [
                connector.id
                for connector in db_session.query(Connector)
                .filter(Connector.source.in_(kg_sources))
                .all()
            ]

        # Get all the documents for the given connectors
        document_ids = [
            cc_pair.id
            for cc_pair in db_session.query(DocumentByConnectorCredentialPair)
            .filter(DocumentByConnectorCredentialPair.connector_id.in_(kg_connectors))
            .all()
        ]

    # Reset the kg fields
    for document_id in document_ids:
        _reset_vespa_for_doc(document_id, tenant_id, index_name)
