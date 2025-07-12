import time
from collections.abc import Callable
from datetime import datetime
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
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.outline_client: OutlineApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.outline_client = OutlineApiClient(
            base_url=credentials["outline_base_url"],
            api_token=credentials["outline_api_token"],
        )
        return None

    @staticmethod
    def _get_doc_batch(
        batch_size: int,
        outline_client: OutlineApiClient,
        endpoint: str,
        transformer: Callable[[OutlineApiClient, dict], Document],
        offset: int,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> tuple[list[Document], int]:
        data: dict[str, Any] = {
            "limit": batch_size,
            "offset": offset,
        }

        # Add date filters if provided
        if start:
            data["dateFilter"] = "updated"
            data["minDate"] = datetime.utcfromtimestamp(start).isoformat()

        if end:
            if "dateFilter" not in data:
                data["dateFilter"] = "updated"
            data["maxDate"] = datetime.utcfromtimestamp(end).isoformat()

        response = outline_client.post(endpoint, data=data)
        batch = response.get("data", [])
        doc_batch = [transformer(outline_client, item) for item in batch]

        return doc_batch, len(batch)

    @staticmethod
    def _collection_to_document(
        outline_client: OutlineApiClient, collection: dict[str, Any]
    ) -> Document:
        collection_id = str(collection.get("id", ""))
        collection.get("url", "")
        title = str(collection.get("name", ""))
        description = collection.get("description", "")

        # Build URL to the collection
        url = outline_client.build_app_url(f"{collection_id}")

        # Combine title and description for text content
        text = title
        if description:
            text += "\n" + description

        updated_at_str = collection.get("updatedAt")

        return Document(
            id="collection:" + collection_id,
            sections=[TextSection(link=url, text=text)],
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
        outline_client: OutlineApiClient, doc: dict[str, Any]
    ) -> Document:
        doc_id = str(doc.get("id", ""))
        title = str(doc.get("title", ""))

        # Get full document content
        try:
            doc_data = outline_client.post("/documents.info", {"id": doc_id})
            full_doc = doc_data.get("data", {})

            # Get the document text (markdown format)
            text_content = full_doc.get("text", "")

            # If no text content, fall back to title and excerpt
            if not text_content:
                text_content = title
                excerpt = doc.get("excerpt", "")
                if excerpt:
                    text_content += "\n" + excerpt
            else:
                # Add title as heading if not already present
                if not text_content.startswith(title):
                    text_content = f"# {title}\n\n{text_content}"

        except OutlineClientRequestFailedError:
            # Fallback if we can't get full document content
            text_content = title
            excerpt = doc.get("excerpt", "")
            if excerpt:
                text_content += "\n" + excerpt

        # Build URL to the document
        url_id = doc.get("url", "")
        url = outline_client.build_app_url(f"{url_id}")

        updated_at_str = doc.get("updatedAt")

        # Add a small delay to avoid rate limiting
        time.sleep(0.1)

        return Document(
            id="document:" + doc_id,
            sections=[TextSection(link=url, text=text_content)],
            source=DocumentSource.OUTLINE,
            semantic_identifier="Document: " + title,
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={
                "type": "document",
                "collection_id": str(doc.get("collectionId", "")),
                "template": str(doc.get("template", False)).lower(),
                "archived": str(doc.get("archivedAt") is not None).lower(),
            },
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.outline_client is None:
            raise ConnectorMissingCredentialError("Outline")

        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.outline_client is None:
            raise ConnectorMissingCredentialError("Outline")

        transform_by_endpoint: dict[
            str, Callable[[OutlineApiClient, dict], Document]
        ] = {
            "/collections.list": self._collection_to_document,
            "/documents.list": self._document_to_document,
        }

        for endpoint, transform in transform_by_endpoint.items():
            offset = 0
            while True:
                doc_batch, num_results = self._get_doc_batch(
                    batch_size=self.batch_size,
                    outline_client=self.outline_client,
                    endpoint=endpoint,
                    transformer=transform,
                    offset=offset,
                    start=start,
                    end=end,
                )
                offset += num_results
                if doc_batch:
                    yield doc_batch

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
            raise ConnectorMissingCredentialError(
                "Outline credentials have not been loaded."
            )

        try:
            # Attempt to fetch auth info to verify credentials
            _ = self.outline_client.post("/auth.info")

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
