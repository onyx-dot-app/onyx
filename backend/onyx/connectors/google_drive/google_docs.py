
from typing import Any

from onyx.connectors.google_utils.resources import (
    get_drive_service,
    get_google_docs_service,
)
from onyx.connectors.google_utils.shared_constants import (
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

def copy_google_doc(
    creds: Any,
    primary_admin_email: str,
    file_id_to_copy: str,
    new_title: str | None = None
) -> dict[str, Any]:
    drive_service = get_drive_service(creds, primary_admin_email)

    body = {}
    if new_title:
        body['name'] = new_title
    copied_file = drive_service.files().copy(
        fileId=file_id_to_copy,
        body=body
    ).execute()

    return copied_file

def read_document(
    creds: Any,
    primary_admin_email: str,
    doc_id: str,
) -> dict[str, Any]:
    """
    Read a Google Doc and return its content.

    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        doc_id: The ID of the Google Doc to read

    Returns:
        dict: The document content and metadata
    """
    try:
        docs_service = get_google_docs_service(creds, primary_admin_email)
        document = docs_service.documents().get(documentId=doc_id).execute()
        return document
    except Exception as e:
        if MISSING_SCOPES_ERROR_STR in str(e):
            raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
        raise e


def write_document(
    creds: Any,
    primary_admin_email: str,
    doc_id: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Write content to a Google Doc using batch update requests.

    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        doc_id: The ID of the Google Doc to write to
        requests: List of update requests to apply to the document

    Returns:
        dict: The response from the batch update operation
    """
    try:
        docs_service = get_google_docs_service(creds, primary_admin_email)
        response = docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests}
        ).execute()
        return response
    except Exception as e:
        if MISSING_SCOPES_ERROR_STR in str(e):
            raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
        raise e


def create_replace_text_request(text_to_find, replacement_text, match_case=True) -> dict[str, Any]:
    """
    Create a request to replace text in a specific range.

    Args:
        text_to_find: The text to find
        replacement_text: The text to replace
        match_case: Whether to match the case of the text to find

    Returns:
        dict: The replace text request
    """
    return {
            'replaceAllText': {
                'containsText': {
                    'text': text_to_find,
                    'matchCase': match_case
                },
                'replaceText': replacement_text,
            }
        }

def create_insert_text_request(text: str, index: int) -> dict[str, Any]:
    """
    Create a request to insert text at a specific position.

    Args:
        text: The text to insert
        index: The position to insert the text at

    Returns:
        dict: The insert text request
    """
    return {
        'insertText': {
            'location': {
                'index': index
            },
            'text': text
        }
    }


def create_delete_text_request(start_index: int, end_index: int) -> dict[str, Any]:
    """
    Create a request to delete text in a specific range.

    Args:
        start_index: The starting position of the text to delete
        end_index: The ending position of the text to delete

    Returns:
        dict: The delete text request
    """
    return {
        'deleteContentRange': {
            'range': {
                'startIndex': start_index,
                'endIndex': end_index
            }
        }
    }


def insert_text(
    creds: Any,
    primary_admin_email: str,
    doc_id: str,
    text: str,
    index: int,
) -> dict[str, Any]:
    """
    Insert text at a specific position in a Google Doc.

    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        doc_id: The ID of the Google Doc to write to
        text: The text to insert
        index: The position to insert the text at

    Returns:
        dict: The response from the batch update operation
    """
    request = create_insert_text_request(text, index)
    return write_document(creds, primary_admin_email, doc_id, [request])


def replace_text(
    creds: Any,
    primary_admin_email: str,
    doc_id: str,
    text_to_find: str,
    replacement_text: str,
    match_case: bool = True,
) -> dict[str, Any]:
    """
    Replace text in a specific range from a Google Doc.

    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        doc_id: The ID of the Google Doc to write to
        text_to_find: The text to find
        replacement_text: The text to replace
        match_case: Whether to match the case of the text to find

    Returns:
        dict: The response from the batch update operation
    """
    request = create_replace_text_request(text_to_find, replacement_text, match_case)
    return write_document(creds, primary_admin_email, doc_id, [request])

def replace_text_batch(
    creds: Any,
    primary_admin_email: str,
    doc_id: str,
    text_to_find: list[str],
    replacement_text: list[str],
    match_case: bool = True,
) -> dict[str, Any]:
    """
    TODO: This uses batch updates but uses case matching which is not optimal. We should instead be
    remembering the location of the text by the indices.

    Replace text in a specific range from a Google Doc.

    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        doc_id: The ID of the Google Doc to write to
        text_to_find: The text to find
        replacement_text: The text to replace
        match_case: Whether to match the case of the text to find

    Returns:
        dict: The response from the batch update operation
    """
    requests = []

    for text, replacement in zip(text_to_find, replacement_text):
        request = create_replace_text_request(text.strip(), replacement.strip(), match_case)
        requests.append(request)
    return write_document(creds, primary_admin_email, doc_id, requests)



def delete_text_range(
    creds: Any,
    primary_admin_email: str,
    doc_id: str,
    start_index: int,
    end_index: int,
) -> dict[str, Any]:
    """
    Delete text in a specific range from a Google Doc.

    Args:
        creds: The credentials to use for authentication
        primary_admin_email: The email of the primary admin
        doc_id: The ID of the Google Doc to write to
        start_index: The starting position of the text to delete
        end_index: The ending position of the text to delete

    Returns:
        dict: The response from the batch update operation
    """
    request = create_delete_text_request(start_index, end_index)
    return write_document(creds, primary_admin_email, doc_id, [request])
