import re

MAX_DOCUMENT_ID_ENCODED_LENGTH: int = 512


class DocumentIDTooLongError(ValueError):
    """Raised when a document ID is too long for OpenSearch after filtering."""


def filter_and_validate_document_id(
    document_id: str, max_encoded_length: int = MAX_DOCUMENT_ID_ENCODED_LENGTH
) -> str:
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
        max_encoded_length: The maximum length of the document ID after
            filtering in bytes. Compared with >= for extra resilience, so
            encoded values of this length will fail.

    Raises:
        DocumentIDTooLongError: If the document ID is too long after filtering.
        ValueError: If the document ID is empty after filtering.

    Returns:
        str: The filtered document ID.
    """
    filtered_document_id = re.sub(r"[^A-Za-z0-9_.\-~]", "", document_id)
    if not filtered_document_id:
        raise ValueError(f"Document ID {document_id} is empty after filtering.")
    if len(filtered_document_id.encode("utf-8")) >= max_encoded_length:
        raise DocumentIDTooLongError(
            f"Document ID {document_id} is too long after filtering."
        )
    return filtered_document_id
