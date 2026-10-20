"""Builders for the failures a targeted reindex test hands to `Resolver.reindex`."""

from onyx.connectors.models import ConnectorFailure, DocumentFailure


def synthetic_failure(document_id: str, link: str | None = None) -> ConnectorFailure:
    """A failure keyed on `document_id`, as the runner builds one from a stored error."""
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=document_id, document_link=link),
        failure_message=f"synthetic failure for {document_id}",
    )
