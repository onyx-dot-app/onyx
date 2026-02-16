import re


def filter_and_validate_document_id(document_id: str) -> str:
    """
    Filters and validates a document ID such that it can be used as an ID in
    OpenSearch.

    OpenSearch imposes the following restrictions on IDs:
    - Must not be an empty string.
    - Must not exceed 512 bytes.
    - Must not contain any control characters (newline, etc.).
    - Must not contain URL-unsafe characters (#, ?, /, %, &, etc.).

    For extra resilience, this function simply removes all characters that are
    not alphanumeric or one of _.-~.

    Any query on document ID should use this function.

    Args:
        document_id: The document ID to filter and validate.

    Raises:
        ValueError: If the document ID is empty or too long after filtering.

    Returns:
        str: The filtered document ID.
    """
    filtered_document_id = re.sub(r"[^A-Za-z0-9_.\-~]", "", document_id)
    if not filtered_document_id:
        raise ValueError(f"Document ID {document_id} is empty after filtering.")
    if len(filtered_document_id.encode("utf-8")) >= 512:
        raise ValueError(f"Document ID {document_id} is too long after filtering.")
    return filtered_document_id
