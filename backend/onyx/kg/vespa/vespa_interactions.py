import json
from collections.abc import Generator

from onyx.document_index.vespa.chunk_retrieval import get_chunks_via_visit_api
from onyx.document_index.vespa.chunk_retrieval import VespaChunkRequest
from onyx.document_index.vespa.index import IndexFilters
from onyx.kg.models import KGChunkFormat
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_document_vespa_contents(
    document_id: str,
    index_name: str,
    tenant_id: str,
    batch_size: int = 8,
) -> Generator[list[KGChunkFormat], None, None]:
    """
    Retrieves chunks from Vespa for the given document IDs and converts them to KGChunks.

    Args:
        document_id (str): ID of the document to fetch chunks for
        index_name (str): Name of the Vespa index
        tenant_id (str): ID of the tenant
        batch_size (int): Number of chunks to fetch per batch

    Yields:
        list[KGChunk]: Batches of chunks ready for KG processing
    """

    current_batch: list[KGChunkFormat] = []

    # get all chunks for the document
    # TODO: revisit the visit function
    chunks = get_chunks_via_visit_api(
        chunk_request=VespaChunkRequest(document_id=document_id),
        index_name=index_name,
        filters=IndexFilters(access_control_list=None, tenant_id=tenant_id),
        field_names=[
            "document_id",
            "chunk_id",
            "title",
            "content",
            "metadata",
            "primary_owners",
            "secondary_owners",
            "source_type",
        ],
        get_large_chunks=False,
    )

    # Convert Vespa chunks to KGChunks
    # kg_chunks: list[KGChunkFormat] = []

    for i, chunk in enumerate(chunks):
        fields = chunk["fields"]
        if isinstance(fields.get("metadata", {}), str):
            fields["metadata"] = json.loads(fields["metadata"])
        current_batch.append(
            KGChunkFormat(
                connector_id=None,  # We may need to adjust this
                document_id=fields.get("document_id"),
                chunk_id=fields.get("chunk_id"),
                primary_owners=fields.get("primary_owners", []),
                secondary_owners=fields.get("secondary_owners", []),
                source_type=fields.get("source_type", ""),
                title=fields.get("title", ""),
                content=fields.get("content", ""),
                metadata=fields.get("metadata", {}),
            )
        )

        if len(current_batch) >= batch_size:
            yield current_batch
            current_batch = []

    # Yield any remaining chunks
    if current_batch:
        yield current_batch
