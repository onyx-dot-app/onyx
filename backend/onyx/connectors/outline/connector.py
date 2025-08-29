"""Outline connector for integrating with Outline knowledge base platform.

This module provides the OutlineConnector class that integrates with Outline
(https://www.getoutline.com/) to index collections and documents into Onyx.
Supports both self-hosted and cloud-hosted Outline instances.
"""

from collections.abc import Generator
from typing import Any

from pydantic.alias_generators import to_snake

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.connectors.outline.client import OutlineApiClient
from onyx.connectors.outline.client import OutlineClientAuthenticationError
from onyx.connectors.outline.client import OutlineClientError
from onyx.connectors.outline.client import OutlineClientRequestFailedError
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OutlineConnector(LoadConnector, PollConnector):
    """Connector for Outline knowledge base platform.

    Integrates with Outline (https://www.getoutline.com/) to index collections
    and documents into the Onyx search system. Supports both self-hosted and
    cloud-hosted Outline instances.

    Features:
    - Full indexing of all collections and documents
    - Incremental polling for updated documents
    - Automatic batching for efficient processing
    - Comprehensive error handling and validation
    - Time-range filtering for polling operations

    The connector creates Onyx documents for both:
    - Collections: Organizational containers with names and descriptions
    - Documents: Individual content items with full text and metadata

    Required credentials:
    - outline_base_url: Base URL of your Outline instance
    - outline_api_token: API token with read access to collections and documents

    Args:
        batch_size: Number of documents to process in each batch (default: INDEX_BATCH_SIZE)
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.outline_client: OutlineApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load and validate Outline API credentials.

        Initializes the Outline API client with the provided credentials and
        performs a test connection to validate the setup.

        Args:
            credentials: Dictionary containing:
                - outline_base_url: Base URL of the Outline instance
                - outline_api_token: Valid API token for authentication

        Returns:
            None if successful

        Raises:
            ConnectorMissingCredentialError: If required credentials are missing
            CredentialExpiredError: If the API token is invalid or expired
            InsufficientPermissionsError: If the token lacks required permissions
            ConnectorValidationError: For other connection or validation errors
        """
        outline_base_url = credentials.get("outline_base_url")
        outline_api_token = credentials.get("outline_api_token")

        if not outline_base_url:
            raise ConnectorMissingCredentialError("outline_base_url")
        if not outline_api_token:
            raise ConnectorMissingCredentialError("outline_api_token")

        try:
            self.outline_client = OutlineApiClient(
                base_url=outline_base_url,
                api_token=outline_api_token,
            )
            # Test connection by attempting to fetch collections
            self.outline_client.get_collections(limit=1)
        except OutlineClientAuthenticationError:
            raise CredentialExpiredError("Outline API token is invalid or expired")
        except OutlineClientRequestFailedError as e:
            if e.status_code == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions for Outline API"
                )
            raise ConnectorValidationError(f"Failed to connect to Outline: {e}")
        except Exception as e:
            raise ConnectorValidationError(f"Failed to initialize Outline client: {e}")

        return None

    def validate_connector_settings(self) -> None:
        """Validate connector settings and test API connectivity.

        Performs a test API call to ensure the connector is properly configured
        and the API client can successfully communicate with Outline.

        Raises:
            ConnectorValidationError: If the client is not initialized
            CredentialExpiredError: If the API token is invalid or expired
            ConnectorValidationError: For other API connectivity issues
        """
        if not self.outline_client:
            raise ConnectorValidationError("Outline client not initialized")

        try:
            # Test API connectivity
            self.outline_client.get_collections(limit=1)
        except OutlineClientAuthenticationError:
            raise CredentialExpiredError("Outline API token is invalid or expired")
        except OutlineClientError as e:
            raise ConnectorValidationError(f"Outline API validation failed: {e}")

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Perform a full index of all documents from Outline.

        Retrieves all collections and their associated documents from the
        Outline workspace, converting them to Onyx documents for indexing.

        Returns:
            Generator yielding batches of Onyx Document objects
        """
        return self._yield_document_batches()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll for documents updated within the specified time range.

        Retrieves only documents and collections that have been modified
        between the start and end timestamps, enabling incremental updates.

        Args:
            start: Start timestamp (seconds since Unix epoch)
            end: End timestamp (seconds since Unix epoch)

        Returns:
            Generator yielding batches of updated Onyx Document objects
        """
        return self._yield_document_batches(start, end)

    def _yield_document_batches(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        """Yield batches of documents within the specified time range.

        Internal method that handles the core document retrieval and batching
        logic. Generates documents from all collections, filters by time range,
        and yields them in configurable batch sizes.

        Args:
            start: Optional start timestamp for filtering (None for full index)
            end: Optional end timestamp for filtering (None for full index)

        Returns:
            Generator yielding batches of Document objects

        Raises:
            ConnectorValidationError: If client is not initialized or API errors occur
            CredentialExpiredError: If authentication fails during processing
            InsufficientPermissionsError: If permissions are insufficient
        """
        if not self.outline_client:
            raise ConnectorValidationError("Outline client not initialized")

        try:
            yield from batch_generator(
                self._generate_documents_stream(start, end), self.batch_size
            )
        except OutlineClientAuthenticationError:
            raise CredentialExpiredError("Outline API token is invalid or expired")
        except OutlineClientRequestFailedError as e:
            if e.status_code == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions for Outline API"
                )
            raise ConnectorValidationError(f"Failed to connect to Outline: {e}")
        except Exception as e:
            logger.error(f"Error fetching documents from Outline: {e}")
            raise ConnectorValidationError(f"Failed to fetch documents: {e}")

    def _generate_documents_stream(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Generator[Document, None, None]:
        """Generate a stream of individual documents from all Outline collections.

        Iterates through all collections in the Outline workspace and processes
        each collection and its documents. Handles pagination automatically for
        both collections and documents within collections.

        Args:
            start: Optional start timestamp for document filtering
            end: Optional end timestamp for document filtering

        Yields:
            Individual Document objects (both collections and documents)

        Raises:
            ConnectorValidationError: If the client is not initialized
        """
        if not self.outline_client:
            raise ConnectorValidationError("Outline client not initialized")

        collections_processed = 0
        collections_offset = 0

        while True:
            collections_response = self.outline_client.get_collections(
                limit=self.batch_size, offset=collections_offset
            )

            collections = collections_response.get("data", [])
            if not collections:
                break

            # Process each collection
            for collection in collections:
                yield from self._process_collection(collection, start, end)

            collections_processed += len(collections)
            collections_offset = collections_processed

            # Check if we've processed all collections
            if len(collections) < self.batch_size:
                break

    def _process_collection(
        self,
        collection: dict[str, Any],
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Generator[Document, None, None]:
        """Process all documents within a single collection.

        Converts the collection itself to a Document object, then retrieves
        and processes all documents within that collection. Handles pagination
        for documents within the collection.

        Args:
            collection: Collection data from the Outline API
            start: Optional start timestamp for document filtering
            end: Optional end timestamp for document filtering

        Yields:
            Document objects for the collection and its contents

        Note:
            Logs warnings for collections without IDs or when document
            retrieval fails, but continues processing other documents.
        """
        if not self.outline_client:
            raise ConnectorValidationError("Outline client not initialized")

        collection_id = collection.get("id")

        if not collection_id:
            logger.warning(f"Collection missing ID: {collection}")
            return

        # Create collection document
        collection_doc = self._collection_to_document(collection)
        if self._document_updated_in_range(collection_doc, start, end):
            yield collection_doc

        # Process documents in the collection
        docs_offset = 0
        docs_processed = 0

        while True:
            try:
                docs_response = self.outline_client.get_collection_documents(
                    collection_id=collection_id,
                    limit=self.batch_size,
                    offset=docs_offset,
                )

                doc_list = docs_response.get("data", [])
                if not doc_list:
                    break

                # Convert each document in the list
                for doc_info in doc_list:
                    doc_id = doc_info.get("id")
                    if not doc_id:
                        continue

                    document = self._document_to_onyx_document(doc_info, collection)

                    if self._document_updated_in_range(document, start, end):
                        yield document

                docs_processed += len(doc_list)
                docs_offset = docs_processed

                # Check if we've processed all documents in collection
                if len(doc_list) < self.batch_size:
                    break

            except OutlineClientRequestFailedError as e:
                logger.warning(
                    f"Error fetching documents from collection {collection_id}: {e}"
                )
                break

    def _collection_to_document(self, collection: dict[str, Any]) -> Document:
        """Convert an Outline collection to an Onyx Document.

        Creates a Document representing the collection itself, including its
        name, description, and metadata. The document content combines the
        collection name and description for searchability.

        Args:
            collection: Collection data from the Outline API containing id, name,
                       description, slug, updatedAt, and other fields

        Returns:
            Document object with collection information and metadata

        Note:
            The document ID uses the format "outline_collection__{collection_id}"
            to distinguish collections from regular documents.
        """
        collection_id = str(collection.get("id", ""))
        name = collection.get("name", "")
        description = collection.get("description", "")

        # Build collection content
        text_content = name
        if description:
            text_content += f"\n\n{description}"

        # Build URL
        if not self.outline_client:
            raise ConnectorMissingCredentialError("Outline client not initialized")
        url = f"{self.outline_client.base_url}/collection/{collection.get('slug', collection_id)}"

        # Parse update time
        updated_at_str = collection.get("updatedAt")
        doc_updated_at = None
        if updated_at_str:
            try:
                doc_updated_at = time_str_to_utc(updated_at_str)
            except Exception as e:
                logger.warning(
                    f"Failed to parse collection update time '{updated_at_str}': {e}"
                )

        # Build metadata
        metadata = {
            "type": "collection",
            "collection_id": collection_id,
            "description": description or "",
        }

        # Add optional metadata fields if available
        if collection.get("archivedAt"):
            metadata["archived_at"] = collection["archivedAt"]

        return Document(
            id=f"outline_collection__{collection_id}",
            sections=[TextSection(link=url, text=text_content)],
            source=DocumentSource.OUTLINE,
            semantic_identifier=f"Collection: {name}",
            title=name,
            doc_updated_at=doc_updated_at,
            metadata=metadata,
        )

    def _document_to_onyx_document(
        self, document: dict[str, Any], collection: dict[str, Any]
    ) -> Document:
        """Convert an Outline document to an Onyx Document.

        Creates a Document representing an individual document with its full
        text content, title, and comprehensive metadata including collection
        context and optional fields like emoji and templates.

        Args:
            document: Document data from the Outline API containing id, title,
                     text, urlId, updatedAt, emoji, and other fields
            collection: Parent collection data for context and metadata

        Returns:
            Document object with document content and metadata

        Note:
            The document ID uses the format "outline_document__{document_id}"
            and includes both document-specific and collection metadata.
        """
        doc_id = str(document.get("id", ""))
        title = document.get("title", "")
        text_content = document.get("text", "")

        # Build document URL
        if not self.outline_client:
            raise ConnectorMissingCredentialError("Outline client not initialized")
        url = f"{self.outline_client.base_url}/doc/{doc_id}"

        # Parse update time
        updated_at_str = document.get("updatedAt")
        doc_updated_at = None
        if updated_at_str:
            try:
                doc_updated_at = time_str_to_utc(updated_at_str)
            except Exception as e:
                logger.warning(
                    f"Failed to parse document update time '{updated_at_str}': {e}"
                )

        # Build metadata
        metadata = {
            "type": "document",
            "collection_id": str(collection.get("id", "")),
            "collection_name": collection.get("name", ""),
            "document_id": doc_id,
        }

        # Add optional metadata fields if available
        for field in ["emoji", "templateId", "template", "publishedAt", "archivedAt"]:
            if document.get(field):
                metadata[to_snake(field)] = document[field]

        return Document(
            id=f"outline_document__{doc_id}",
            sections=[TextSection(link=url, text=text_content)],
            source=DocumentSource.OUTLINE,
            semantic_identifier=f"Document: {title}",
            title=title,
            doc_updated_at=doc_updated_at,
            metadata=metadata,
        )

    def _document_updated_in_range(
        self,
        document: Document,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> bool:
        """Check if a document was updated within the specified time range.

        Determines whether a document should be included based on its update
        timestamp and the provided time range. Handles special cases for
        documents without update times.

        Args:
            document: The Document object to check
            start: Optional start timestamp (None means no start limit)
            end: Optional end timestamp (None means no end limit)

        Returns:
            True if the document should be included, False otherwise

        Note:
            Documents without update times are included during full loads
            (start=None) but excluded during polling operations to avoid
            repeatedly processing unchanged content.
        """
        if start is None and end is None:
            return True

        doc_updated_at = document.doc_updated_at
        if doc_updated_at is None:
            # If no update time, include during full load but not during polling
            return start is None

        if start is not None and doc_updated_at.timestamp() < start:
            return False

        if end is not None and doc_updated_at.timestamp() > end:
            return False

        return True
