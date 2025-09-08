import html
import time
from collections.abc import Callable
from typing import Any

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
from onyx.connectors.outline.client import OutlineClientRequestFailedError


class OutlineConnector(LoadConnector, PollConnector):
    """Connector for Outline knowledge base. Handles authentication, document loading and polling.
    Implements both LoadConnector for initial state loading and PollConnector for incremental updates.
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.outline_client: OutlineApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        required_keys = ["outline_api_token", "outline_base_url"]
        for key in required_keys:
            if key not in credentials:
                raise ConnectorMissingCredentialError("Outline")

        self.outline_client = OutlineApiClient(
            api_token=credentials["outline_api_token"],
            base_url=credentials["outline_base_url"],
        )
        return None

    @staticmethod
    def _get_doc_batch(
        batch_size: int,
        outline_client: OutlineApiClient,
        endpoint: str,
        transformer: Callable[[OutlineApiClient, dict], Document],
        start_ind: int,
    ) -> tuple[list[Document], int]:
        data = {
            "limit": batch_size,
            "offset": start_ind,
        }

        batch = outline_client.post(endpoint, data=data).get("data", [])
        doc_batch = [transformer(outline_client, item) for item in batch]

        return doc_batch, len(batch)

    @staticmethod
    def _collection_to_document(
        outline_client: OutlineApiClient, collection: dict[str, Any]
    ) -> Document:
        url = outline_client.build_app_url(f"/collection/{collection.get('id')}")
        title = str(collection.get("name", ""))
        name = collection.get("name") or ""
        description = collection.get("description") or ""
        text = name + "\n" + description
        updated_at_str = (
            str(collection.get("updatedAt"))
            if collection.get("updatedAt") is not None
            else None
        )
        return Document(
            id="outline_collection__" + str(collection.get("id")),
            sections=[TextSection(link=url, text=html.unescape(text))],
            source=DocumentSource.OUTLINE,
            semantic_identifier="Collection: " + title,
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={"type": "collection"},
        )

    @staticmethod
    def _document_to_document(
        outline_client: OutlineApiClient, document: dict[str, Any]
    ) -> Document:
        url = outline_client.build_app_url(f"/doc/{document.get('id')}")
        title = str(document.get("title", ""))
        doc_title = document.get("title") or ""
        doc_text = document.get("text") or ""
        text = doc_title + "\n" + doc_text
        updated_at_str = (
            str(document.get("updatedAt"))
            if document.get("updatedAt") is not None
            else None
        )
        return Document(
            id="outline_document__" + str(document.get("id")),
            sections=[TextSection(link=url, text=html.unescape(text))],
            source=DocumentSource.OUTLINE,
            semantic_identifier="Document: " + title,
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={"type": "document"},
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.outline_client is None:
            raise ConnectorMissingCredentialError("Outline")

        return self._fetch_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.outline_client is None:
            raise ConnectorMissingCredentialError("Outline")

        # Outline API does not support date-based filtering natively,
        # so we implement client-side filtering after fetching documents
        def time_filter(doc: Document) -> bool:
            if doc.doc_updated_at is None:
                return False
            doc_timestamp = doc.doc_updated_at.timestamp()
            if doc_timestamp < start:
                return False
            if doc_timestamp > end:
                return False
            return True

        return self._fetch_documents(time_filter)

    def _fetch_documents(
        self, time_filter: Callable[[Document], bool] | None = None
    ) -> GenerateDocumentsOutput:
        if self.outline_client is None:
            raise ConnectorMissingCredentialError("Outline")

        transform_by_endpoint: dict[
            str, Callable[[OutlineApiClient, dict], Document]
        ] = {
            "documents.list": self._document_to_document,
            "collections.list": self._collection_to_document,
        }

        for endpoint, transform in transform_by_endpoint.items():
            start_ind = 0
            while True:
                doc_batch, num_results = self._get_doc_batch(
                    batch_size=self.batch_size,
                    outline_client=self.outline_client,
                    endpoint=endpoint,
                    transformer=transform,
                    start_ind=start_ind,
                )

                # Apply time filtering if specified
                filtered_batch = []
                for doc in doc_batch:
                    if time_filter is None or time_filter(doc):
                        filtered_batch.append(doc)

                start_ind += num_results
                if filtered_batch:
                    yield filtered_batch

                if num_results < self.batch_size:
                    break
                else:
                    time.sleep(0.2)

    def validate_connector_settings(self) -> None:
        """
        Validate that the Outline credentials and connector settings are correct.
        Specifically checks that we can make an authenticated request to Outline.
        """
        if not self.outline_client:
            raise ConnectorMissingCredentialError("Outline")

        try:
            # Use auth.info endpoint for validation
            _ = self.outline_client.post("auth.info", data={})

        except OutlineClientRequestFailedError as e:
            # Check for HTTP status codes
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "Your Outline credentials appear to be invalid or expired (HTTP 401)."
                ) from e
            elif e.status_code == 403:
                raise InsufficientPermissionsError(
                    "The configured Outline token does not have sufficient permissions (HTTP 403)."
                ) from e
            else:
                raise ConnectorValidationError(
                    f"Unexpected Outline error (status={e.status_code}): {e}"
                ) from e

        except Exception as exc:
            raise ConnectorValidationError(
                f"Unexpected error while validating Outline connector settings: {exc}"
            ) from exc
