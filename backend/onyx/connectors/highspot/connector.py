import os
from datetime import datetime
from io import BytesIO
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.highspot.client import HighspotClient
from onyx.connectors.highspot.client import HighspotClientError
from onyx.connectors.highspot.utils import scrape_url_content
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()
_SLIM_BATCH_SIZE = 1000


class HighspotSpot(BaseModel):
    id: str
    name: str


class HighspotConnector(LoadConnector, PollConnector, SlimConnectorWithPermSync):
    """
    Connector for loading data from Highspot.

    Retrieves content from specified spots using the Highspot API.
    If no spots are specified, retrieves content from all available spots.
    """

    def __init__(
        self,
        spot_names: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ):
        """
        Initialize the Highspot connector.

        Args:
            spot_names: List of spot names to retrieve content from (if empty, gets all spots)
            batch_size: Number of items to retrieve in each batch
        """
        self.spot_names = spot_names or []
        self.batch_size = batch_size

        self._client: Optional[HighspotClient] = None
        self.highspot_url: Optional[str] = None
        self.key: Optional[str] = None
        self.secret: Optional[str] = None

    @property
    def client(self) -> HighspotClient:
        if self._client is None:
            if not self.key or not self.secret:
                raise ConnectorMissingCredentialError("Highspot")
            # Ensure highspot_url is a string, use default if None
            base_url = (
                self.highspot_url
                if self.highspot_url is not None
                else HighspotClient.BASE_URL
            )
            self._client = HighspotClient(self.key, self.secret, base_url=base_url)
        return self._client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        logger.info("Loading Highspot credentials")
        self.highspot_url = credentials.get("highspot_url")
        self.key = credentials.get("highspot_key")
        self.secret = credentials.get("highspot_secret")
        return None

    def _fetch_spots(self) -> list[HighspotSpot]:
        """
        Populate the spot ID map with all available spots.
        Keys are stored as lowercase for case-insensitive lookups.
        """
        return [
            HighspotSpot(id=spot["id"], name=spot["title"])
            for spot in self.client.get_spots()
        ]

    def _fetch_spots_to_process(self) -> list[HighspotSpot]:
        """
        Fetch spots to process based on the configured spot names.
        """
        spots = self._fetch_spots()
        if not spots:
            raise ValueError("No spots found in Highspot.")

        if self.spot_names:
            lower_spot_names = [name.lower() for name in self.spot_names]
            spots_to_process = [
                spot for spot in spots if spot.name.lower() in lower_spot_names
            ]
            if not spots_to_process:
                raise ValueError(
                    f"No valid spots found in Highspot. Found {spots} but {self.spot_names} were requested."
                )
            return spots_to_process

        return spots

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Load content from configured spots in Highspot.
        If no spots are configured, loads from all spots.

        Yields:
            Batches of Document objects
        """
        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        """
        Poll Highspot for content updated since the start time.

        Args:
            start: Start time as seconds since Unix epoch
            end: End time as seconds since Unix epoch

        Yields:
            Batches of Document objects
        """
        spots_to_process = self._fetch_spots_to_process()

        doc_batch: list[Document | HierarchyNode] = []
        try:
            for spot in spots_to_process:
                try:
                    offset = 0
                    has_more = True

                    while has_more:
                        logger.info(
                            "Retrieving items from spot %s, offset %s",
                            spot.name,
                            offset,
                        )
                        response = self.client.get_spot_items(
                            spot_id=spot.id, offset=offset, page_size=self.batch_size
                        )
                        items = response.get("collection", [])
                        logger.info(
                            "Received %s items from spot %s", len(items), spot.name
                        )
                        if not items:
                            has_more = False
                            continue

                        for item in items:
                            try:
                                item_id = item.get("id")
                                if not item_id:
                                    logger.warning("Item without ID found, skipping")
                                    continue

                                item_details = self.client.get_item(item_id)
                                if not item_details:
                                    logger.warning(
                                        "Item %s details not found, skipping", item_id
                                    )
                                    continue
                                # Apply time filter if specified
                                if start or end:
                                    updated_at = item_details.get("date_updated")
                                    if updated_at:
                                        # Convert to datetime for comparison
                                        try:
                                            updated_time = datetime.fromisoformat(
                                                updated_at.replace("Z", "+00:00")
                                            )
                                            if (
                                                start
                                                and updated_time.timestamp() < start
                                            ) or (
                                                end and updated_time.timestamp() > end
                                            ):
                                                continue
                                        except (ValueError, TypeError):
                                            # Skip if date cannot be parsed
                                            logger.warning(
                                                "Invalid date format for item %s: %s",
                                                item_id,
                                                updated_at,
                                            )
                                            continue

                                content = self._get_item_content(item_details)

                                title = item_details.get("title", "")

                                doc_batch.append(
                                    Document(
                                        id=f"HIGHSPOT_{item_id}",
                                        sections=[
                                            TextSection(
                                                link=item_details.get(
                                                    "url",
                                                    f"https://www.highspot.com/items/{item_id}",
                                                ),
                                                text=content,
                                            )
                                        ],
                                        source=DocumentSource.HIGHSPOT,
                                        semantic_identifier=title,
                                        metadata={
                                            "spot_name": spot.name,
                                            "type": item_details.get(
                                                "content_type", ""
                                            ),
                                            "created_at": item_details.get(
                                                "date_added", ""
                                            ),
                                            "author": item_details.get("author", ""),
                                            "language": item_details.get(
                                                "language", ""
                                            ),
                                            "can_download": str(
                                                item_details.get("can_download", False)
                                            ),
                                        },
                                        doc_updated_at=item_details.get("date_updated"),
                                    )
                                )

                                if len(doc_batch) >= self.batch_size:
                                    yield doc_batch
                                    doc_batch = []

                            except HighspotClientError as e:
                                item_id = (
                                    "ID"
                                    if not item_id  # ty: ignore[possibly-unresolved-reference]
                                    else item_id  # ty: ignore[possibly-unresolved-reference]
                                )
                                logger.error(
                                    "Error retrieving item %s: %s", item_id, str(e)
                                )
                            except Exception as e:
                                item_id = (
                                    "ID"
                                    if not item_id  # ty: ignore[possibly-unresolved-reference]
                                    else item_id  # ty: ignore[possibly-unresolved-reference]
                                )
                                logger.error(
                                    "Unexpected error for item %s: %s", item_id, str(e)
                                )

                        has_more = len(items) >= self.batch_size
                        offset += self.batch_size

                except (HighspotClientError, ValueError) as e:
                    logger.error("Error processing spot %s: %s", spot.name, str(e))
                    raise
                except Exception as e:
                    logger.error(
                        "Unexpected error processing spot %s: %s", spot.name, str(e)
                    )
                    raise

        except Exception as e:
            logger.error("Error in Highspot connector: %s", str(e))
            raise

        if doc_batch:
            yield doc_batch

    def _get_item_content(self, item_details: Dict[str, Any]) -> str:
        """
        Get the text content of an item.

        Args:
            item_details: Item details from the API

        Returns:
            Text content of the item
        """
        item_id = item_details.get("id", "")
        content_name = item_details.get("content_name", "")
        is_valid_format = content_name and "." in content_name
        file_extension = content_name.split(".")[-1].lower() if is_valid_format else ""
        file_extension = "." + file_extension if file_extension else ""
        can_download = item_details.get("can_download", False)
        content_type = item_details.get("content_type", "")

        # Extract title and description once at the beginning
        title, description = self._extract_title_and_description(item_details)
        default_content = f"{title}\n{description}"
        logger.info(
            "Processing item %s with extension %s and file name %s",
            item_id,
            file_extension,
            content_name,
        )

        try:
            if content_type == "WebLink":
                url = item_details.get("url")
                if not url:
                    return default_content
                content = scrape_url_content(url, True)
                return content if content else default_content

            elif (
                is_valid_format
                and file_extension in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
                and can_download
            ):
                content_response = self.client.get_item_content(item_id)
                # Process and extract text from binary content based on type
                if content_response:
                    text_content = extract_file_text(
                        BytesIO(content_response), content_name, False
                    )
                    return text_content if text_content else default_content
                return default_content

            else:
                logger.warning(
                    "Item %s has unsupported format: %s", item_id, file_extension
                )
                return default_content

        except HighspotClientError as e:
            error_context = f"item {item_id}" if item_id else "(item id not found)"
            logger.warning(
                "Could not retrieve content for %s: %s", error_context, str(e)
            )
            return default_content
        except ValueError as e:
            error_context = f"item {item_id}" if item_id else "(item id not found)"
            logger.error("Value error for %s: %s", error_context, str(e))
            return default_content

        except Exception as e:
            error_context = f"item {item_id}" if item_id else "(item id not found)"
            logger.error(
                "Unexpected error retrieving content for %s: %s", error_context, str(e)
            )
            return default_content

    def _extract_title_and_description(
        self, item_details: Dict[str, Any]
    ) -> tuple[str, str]:
        """
        Extract the title and description from item details.

        Args:
            item_details: Item details from the API

        Returns:
            Tuple of title and description
        """
        title = item_details.get("title", "")
        description = item_details.get("description", "")
        return title, description

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        """
        Retrieve all document IDs from the configured spots.
        If no spots are configured, retrieves from all spots.

        Args:
            start: Optional start time filter
            end: Optional end time filter
            callback: Optional indexing heartbeat callback

        Yields:
            Batches of SlimDocument objects
        """
        spots_to_process = self._fetch_spots_to_process()

        slim_doc_batch: list[SlimDocument | HierarchyNode] = []
        try:
            for spot in spots_to_process:
                try:
                    offset = 0
                    has_more = True

                    while has_more:
                        logger.info(
                            "Retrieving slim documents from spot %s, offset %s",
                            spot.name,
                            offset,
                        )
                        response = self.client.get_spot_items(
                            spot_id=spot.id, offset=offset, page_size=self.batch_size
                        )

                        items = response.get("collection", [])
                        if not items:
                            has_more = False
                            continue

                        for item in items:
                            item_id = item.get("id")
                            if not item_id:
                                logger.warning("Item without ID found, skipping")
                                continue

                            slim_doc_batch.append(
                                SlimDocument(id=f"HIGHSPOT_{item_id}")
                            )

                            if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                                yield slim_doc_batch
                                slim_doc_batch = []

                        has_more = len(items) >= self.batch_size
                        offset += self.batch_size

                except (HighspotClientError, ValueError):
                    logger.exception(
                        "Error retrieving slim documents from spot %s", spot.name
                    )
                    raise

            if slim_doc_batch:
                yield slim_doc_batch
        except Exception:
            logger.exception("Error in Highspot Slim Connector")
            raise

    def validate_credentials(self) -> bool:
        """
        Validate that the provided credentials can access the Highspot API.

        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            return self.client.health_check()
        except Exception as e:
            logger.error("Failed to validate credentials: %s", str(e))
            return False


if __name__ == "__main__":
    spot_names: List[str] = []
    connector = HighspotConnector(spot_names)
    credentials = {
        "highspot_key": os.environ.get("HIGHSPOT_KEY"),
        "highspot_secret": os.environ.get("HIGHSPOT_SECRET"),
    }
    connector.load_credentials(credentials=credentials)
    for doc in connector.load_from_state():
        print(doc)
