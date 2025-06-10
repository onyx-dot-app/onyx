import uuid
from datetime import datetime
from datetime import timezone

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection


def create_test_document(
    doc_id: str | None = None,
    text: str = "Test content",
    link: str = "http://test.com",
    source: DocumentSource = DocumentSource.MOCK_CONNECTOR,
    metadata: dict | None = None,
) -> Document:
    """Create a test document with the given parameters.

    Args:
        doc_id: Optional document ID. If not provided, a random UUID will be generated.
        text: The text content of the document. Defaults to "Test content".
        link: The link for the document section. Defaults to "http://test.com".
        source: The document source. Defaults to MOCK_CONNECTOR.
        metadata: Optional metadata dictionary. Defaults to empty dict.
    """
    doc_id = doc_id or f"test-doc-{uuid.uuid4()}"
    return Document(
        id=doc_id,
        sections=[TextSection(text=text, link=link)],
        source=source,
        semantic_identifier=doc_id,
        doc_updated_at=datetime.now(timezone.utc),
        metadata=metadata or {},
    )


def create_test_document_failure(
    doc_id: str,
    failure_message: str = "Simulated failure",
    document_link: str | None = None,
) -> ConnectorFailure:
    """Create a test document failure with the given parameters.

    Args:
        doc_id: The ID of the document that failed.
        failure_message: The failure message. Defaults to "Simulated failure".
        document_link: Optional link to the failed document.
    """
    return ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=doc_id,
            document_link=document_link,
        ),
        failure_message=failure_message,
    )
