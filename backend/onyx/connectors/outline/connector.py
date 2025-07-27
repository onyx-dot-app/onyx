import time
from datetime import datetime
from typing import Any
from typing import Callable

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
from onyx.file_processing.html_utils import parse_html_page_basic


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
        start_ind: int,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> tuple[list[Document], int]:
        data = {
            "limit": batch_size,
            "offset": start_ind,
        }

        # Add date filters if provided
        if start:
            # Outline uses ISO format for date filtering
            data["updatedAt"] = {
                "gte": datetime.utcfromtimestamp(start).isoformat() + "Z"
            }
        if end:
            if "updatedAt" not in data:
                data["updatedAt"] = {}
            data["updatedAt"]["lte"] = datetime.utcfromtimestamp(end).isoformat() + "Z"

        response = outline_client.post(endpoint, data)
        batch = response.get("data", [])
        doc_batch = [transformer(outline_client, item) for item in batch]

        return doc_batch, len(batch)

    @staticmethod
    def _collection_to_document(
        outline_client: OutlineApiClient, collection: dict[str, Any]
    ) -> Document:
        collection_id = str(collection.get("id", ""))
        url = outline_client.build_app_url(f"/collection/{collection.get('urlId', collection_id)}")
        title = str(collection.get("name", ""))
        description = collection.get("description", "")
        text = f"{title}\n{description}" if description else title
        
        updated_at_str = collection.get("updatedAt")
        
        return Document(
            id=f"collection__{collection_id}",
            sections=[TextSection(link=url, text=text)],
            source=DocumentSource.OUTLINE,
            semantic_identifier=f"Collection: {title}",
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str else None
            ),
            metadata={"type": "collection"},
        )

    @staticmethod
    def _document_to_document(
        outline_client: OutlineApiClient, document: dict[str, Any]
    ) -> Document:
        document_id = str(document.get("id", ""))
        url_id = document.get("urlId", document_id)
        url = outline_client.build_app_url(f"/doc/{url_id}")
        title = str(document.get("title", ""))
        
        # Get the document content - Outline stores content in 'text' field as markdown
        text_content = document.get("text", "")
        if not text_content and document.get("id"):
            # If text is not included, we might need to fetch it separately
            try:
                doc_detail = outline_client.post("documents.info", {"id": document_id})
                text_content = doc_detail.get("data", {}).get("text", "")
            except Exception:
                # If we can't fetch the content, use title as fallback
                text_content = title
        
        # Parse HTML content if needed (Outline can contain HTML in markdown)
        if text_content:
            try:
                parsed_text = parse_html_page_basic(text_content)
                if parsed_text.strip():
                    text_content = parsed_text
            except Exception:
                # If parsing fails, use original content
                pass
        
        updated_at_str = document.get("updatedAt")
        
        # Add a small delay to avoid rate limiting
        time.sleep(0.1)
        
        return Document(
            id=f"document__{document_id}",
            sections=[TextSection(link=url, text=text_content or title)],
            source=DocumentSource.OUTLINE,
            semantic_identifier=f"Document: {title}",
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str else None
            ),
            metadata={
                "type": "document",
                "collection_id": document.get("collectionId", ""),
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
            "collections.list": self._collection_to_document,
            "documents.list": self._document_to_document,
        }

        for endpoint, transformer in transform_by_endpoint.items():
            start_ind = 0
            while True:
                doc_batch, batch_size = self._get_doc_batch(
                    self.batch_size,
                    self.outline_client,
                    endpoint,
                    transformer,
                    start_ind,
                    start,
                    end,
                )

                if doc_batch:
                    yield doc_batch

                if batch_size < self.batch_size:
                    break

                start_ind += batch_size

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
            _ = self.outline_client.post("auth.info")

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
