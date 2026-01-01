import json

from onyx.context.search.models import InferenceSection


def convert_inference_sections_to_llm_string(
    top_sections: list[InferenceSection],
    citation_start: int = 1,
    limit: int | None = None,
    include_source_type: bool = True,
    include_link: bool = False,
    include_document_id: bool = False,
) -> tuple[str, dict[int, str]]:
    """Convert InferenceSection objects to a JSON string for LLM.

    Returns a JSON string with document results and a citation mapping.
    """
    # Apply limit if specified
    if limit is not None:
        top_sections = top_sections[:limit]

    # Group sections by document_id to assign same citation_id to sections from same document
    document_id_to_citation_id: dict[str, int] = {}
    citation_mapping: dict[int, str] = {}
    current_citation_id = citation_start

    # First pass: assign citation_ids to unique document_ids
    for section in top_sections:
        document_id = section.center_chunk.document_id
        if document_id not in document_id_to_citation_id:
            document_id_to_citation_id[document_id] = current_citation_id
            citation_mapping[current_citation_id] = document_id
            current_citation_id += 1

    # Second pass: build results with citation_ids assigned per document
    results = []

    for section in top_sections:
        chunk = section.center_chunk
        document_id = chunk.document_id
        citation_id = document_id_to_citation_id[document_id]

        # Combine primary and secondary owners for authors
        authors = None
        if chunk.primary_owners or chunk.secondary_owners:
            authors = []
            if chunk.primary_owners:
                authors.extend(chunk.primary_owners)
            if chunk.secondary_owners:
                authors.extend(chunk.secondary_owners)

        # Format updated_at as ISO string if available
        updated_at_str = None
        if chunk.updated_at:
            updated_at_str = chunk.updated_at.isoformat()

        # Build result dictionary in desired order, only including non-None/empty fields
        result = {
            "document": citation_id,
            "title": chunk.semantic_identifier,
        }
        if updated_at_str is not None:
            result["updated_at"] = updated_at_str
        if authors is not None:
            result["authors"] = authors
        if include_source_type:
            result["source_type"] = chunk.source_type.value
        if include_link:
            # Get the first link from the center chunk's source_links dict
            link = None
            if chunk.source_links:
                # source_links is dict[int, str], get the first value
                link = next(iter(chunk.source_links.values()), None)
            if link:
                result["url"] = link
        if include_document_id and "url" not in result:
            result["document_identifier"] = chunk.document_id
        if chunk.metadata:
            result["metadata"] = json.dumps(chunk.metadata)
        result["content"] = section.combined_content
        results.append(result)

    return json.dumps({"results": results}, indent=4), citation_mapping
