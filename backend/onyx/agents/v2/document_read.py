"""Read bounded pages from a previously cited document via the Onyx index."""

import json

from onyx.agents.v2.models import ToolOutput
from onyx.db.harness_v2 import document_read_filters
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)


def read_cited_document(
    *, index, user, filters, known_citations, read_citation, start_chunk, citation
):
    document = known_citations.get(read_citation)
    if document is None:
        return ToolOutput(
            status="error",
            content="Unknown citation. Use a numeric citation returned by a search in this task.",
            receipt={"operation": "read_document"},
        )
    chunks = index.id_based_retrieval(
        chunk_requests=[
            DocumentSectionRequest(
                document_id=replace_invalid_doc_id_characters(document),
                min_chunk_ind=start_chunk,
                max_chunk_ind=start_chunk + 5,
            )
        ],
        filters=document_read_filters(user, filters),
        batch_retrieval=True,
    )
    chunks = sorted(chunks, key=lambda c: c.chunk_id)
    if not chunks:
        return ToolOutput(
            status="partial",
            content="No authorized chunks returned for this page.",
            receipt={
                "operation": "read_document",
                "read_citation": read_citation,
                "start_chunk": start_chunk,
            },
        )
    return ToolOutput(
        content=json.dumps(
            {
                "results": [
                    {
                        "document": citation,
                        "document_id": document,
                        "chunk_id": c.chunk_id,
                        "title": c.semantic_identifier,
                        "source_type": c.source_type.value,
                        "content": c.content,
                    }
                    for c in chunks
                ]
            },
            ensure_ascii=False,
        ),
        document_ids=[document],
        citation_mapping={citation: document},
        receipt={
            "operation": "read_document",
            "read_citation": read_citation,
            "start_chunk": start_chunk,
            "returned_chunks": [c.chunk_id for c in chunks],
            "next_chunk": chunks[-1].chunk_id + 1 if len(chunks) >= 6 else None,
            "coverage": "Authorized page of at most six chunks; no query expansion or model call.",
        },
    )
