import logging
from datetime import datetime
from io import BytesIO
from typing import Any
from typing import Dict
from typing import List

from onyx.background.celery.versioned_apps.primary import app as primary_app
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.highspot.client import HighspotClient
from onyx.connectors.highspot.client import HighspotClientError
from onyx.connectors.highspot.utils import scrape_url_content
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.file_processing.extract_file_text import AUDIO_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import IMAGE_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import VALID_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import VIDEO_FILE_EXTENSIONS
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()
logger.setLevel(logging.DEBUG)
_SLIM_BATCH_SIZE = 1000


class HighspotConnector(LoadConnector, PollConnector, SlimConnector):
    """
    Connector for loading data from Highspot.

    Retrieves content from specified spots using the Highspot API.
    If no spots are specified, retrieves content from all available spots.
    """

    def __init__(
        self,
        spot_names: List[str] = [],
        batch_size: int = INDEX_BATCH_SIZE,
    ):
        """
        Initialize the Highspot connector.

        Args:
            spot_names: List of spot names to retrieve content from (if empty, gets all spots)
            batch_size: Number of items to retrieve in each batch
        """
        self.spot_names = spot_names
        self.batch_size = batch_size
        self._client = None
        self._spot_id_map = {}  # Maps spot names to spot IDs
        self._all_spots_fetched = False

    @property
    def client(self):
        if self._client is None:
            if not self.key or not self.secret:
                raise ConnectorMissingCredentialError("Highspot")
            self._client = HighspotClient(self.key, self.secret)
        return self._client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        logger.info("Loading Highspot credentials")
        self.key = credentials.get("highspot_key")
        self.secret = credentials.get("highspot_secret")
        return None

    def _get_all_spot_names(self) -> List[str]:
        """
        Retrieve all available spot names.

        Returns:
            List of all spot names
        """
        spot_names = []
        spots = self.client.get_spots()
        for spot in spots:
            if "title" in spot and "id" in spot:
                spot_name = spot["title"]
                spot_names.append(spot_name)
                self._spot_id_map[spot_name] = spot["id"]

        self._all_spots_fetched = True
        logger.info(f"Retrieved {len(spot_names)} spots from Highspot")
        return spot_names

    def _get_spot_id_from_name(self, spot_name: str) -> str:
        """
        Get spot ID from a spot name.

        Args:
            spot_name: Name of the spot

        Returns:
            ID of the spot

        Raises:
            ValueError: If spot name is not found
        """
        if not self._all_spots_fetched and not self._spot_id_map:
            # Initialize the map if it's empty
            spots = self.client.get_spots()
            for spot in spots:
                if "title" in spot and "id" in spot:
                    self._spot_id_map[spot["title"]] = spot["id"]
            self._all_spots_fetched = True

        if spot_name not in self._spot_id_map:
            raise ValueError(f"Spot '{spot_name}' not found")

        return self._spot_id_map[spot_name]

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
        doc_batch: list[Document] = []

        # If no spots specified, get all spots
        spot_names_to_process = self.spot_names
        if not spot_names_to_process:
            spot_names_to_process = self._get_all_spot_names()
            logger.info(
                f"No spots specified, using all {len(spot_names_to_process)} available spots"
            )
        # NOTE: Handle for spots doesn't have access to
        for spot_name in spot_names_to_process:
            try:
                spot_id = self._get_spot_id_from_name(spot_name)
                page = 0
                has_more = True

                while has_more:
                    logger.info(f"Retrieving items from spot {spot_name}, page {page}")
                    response = self.client.get_spot_items(
                        spot_id=spot_id, page=page, page_size=self.batch_size
                    )
                    items = response.get("collection", [])
                    logger.info(f"Received Items: {items}")
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
                                            start and updated_time.timestamp() < start
                                        ) or (end and updated_time.timestamp() > end):
                                            continue
                                    except (ValueError, TypeError):
                                        # Skip if date cannot be parsed
                                        logger.warning(
                                            f"Invalid date format for item {item_id}: {updated_at}"
                                        )
                                        continue

                            content = self._get_item_content(item_details)
                            title = item_details.get("title", "")

                            doc_batch.append(
                                Document(
                                    id=f"HIGHSPOT_{item_id}",
                                    sections=[
                                        Section(
                                            link=item_details.get(
                                                "url",
                                                f"https://www.highspot.com/{item_id}",
                                            ),
                                            text=content,
                                        )
                                    ],
                                    source=DocumentSource.HIGHSPOT,
                                    semantic_identifier=title,
                                    metadata={
                                        "spot_name": spot_name,
                                        "type": item_details.get("content_type", ""),
                                        "created_at": item_details.get("date_added"),
                                        "updated_at": item_details.get("date_updated"),
                                    },
                                    doc_updated_at=item_details.get("date_updated"),
                                )
                            )

                            if len(doc_batch) >= self.batch_size:
                                yield doc_batch
                                doc_batch = []

                        except HighspotClientError as e:
                            logger.error(f"Error retrieving item {item_id}: {str(e)}")

                    has_more = len(items) >= self.batch_size
                    page += 1

            except (HighspotClientError, ValueError) as e:
                logger.error(f"Error processing spot {spot_name}: {str(e)}")

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
        file_extension = (
            content_name.split(".")[-1].lower()
            if content_name and "." in content_name
            else ""
        )
        file_extension = "." + file_extension if file_extension else ""
        logger.info(f"Processing item {item_id} with extension {file_extension}")
        content_type = item_details.get("content_type", "")
        try:
            if content_type == "WebLink":
                url = item_details.get("url")
                if not url:
                    return ""
                content = scrape_url_content(url, True)
                return content if content else ""

            elif (
                file_extension in VIDEO_FILE_EXTENSIONS
                or file_extension in AUDIO_FILE_EXTENSIONS
                or file_extension in IMAGE_FILE_EXTENSIONS
            ):
                # For media files, use the title and description
                title = item_details.get("title", "")
                description = item_details.get("description", "")
                content = f"{title}\n{description}"
                return content

            elif file_extension in VALID_FILE_EXTENSIONS:
                # For documents, try to get the text content
                content_response = self.client.get_item_content(item_id)
                # Process and extract text from binary content based on type
                if content_response:
                    text_content, _ = extract_text_and_images(
                        BytesIO(content_response), content_name
                    )
                    return text_content
                return ""
            else:
                # For other types, use the description or a default message
                return item_details.get("description", "No text content available")
        except HighspotClientError as e:
            logger.warning(f"Could not retrieve content for item {item_id}: {str(e)}")
            return ""

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
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
        slim_doc_batch: list[SlimDocument] = []

        # If no spots specified, get all spots
        spot_names_to_process = self.spot_names
        if not spot_names_to_process:
            spot_names_to_process = self._get_all_spot_names()
            logger.info(
                f"No spots specified, using all {len(spot_names_to_process)} available spots for slim documents"
            )

        for spot_name in spot_names_to_process:
            try:
                spot_id = self._get_spot_id_from_name(spot_name)
                page = 1
                has_more = True

                while has_more:
                    if callback:
                        callback.heartbeat()

                    logger.info(
                        f"Retrieving slim documents from spot {spot_name}, page {page}"
                    )
                    response = self.client.get_spot_items(
                        spot_id=spot_id, page=page, page_size=self.batch_size
                    )

                    items = response.get("collection", [])
                    if not items:
                        has_more = False
                        continue

                    for item in items:
                        item_id = item.get("id")
                        if not item_id:
                            continue

                        # Apply time filter if specified
                        if start or end:
                            # Get item details for timestamp checking
                            try:
                                item_details = self.client.get_item(item_id)
                                updated_at = item_details.get("updatedAt")
                                if updated_at:
                                    # Convert to datetime for comparison
                                    updated_time = datetime.fromisoformat(
                                        updated_at.replace("Z", "+00:00")
                                    )
                                    if (start and updated_time.timestamp() < start) or (
                                        end and updated_time.timestamp() > end
                                    ):
                                        continue
                            except HighspotClientError:
                                # Skip if we can't get item details
                                continue

                        slim_doc_batch.append(SlimDocument(id=f"HIGHSPOT_{item_id}"))

                        if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                            yield slim_doc_batch
                            slim_doc_batch = []

                    has_more = len(items) >= self.batch_size
                    page += 1

            except (HighspotClientError, ValueError) as e:
                logger.error(
                    f"Error retrieving slim documents from spot {spot_name}: {str(e)}"
                )

        if slim_doc_batch:
            yield slim_doc_batch

    def validate_credentials(self) -> bool:
        """
        Validate that the provided credentials can access the Highspot API.

        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            return self.client.health_check()
        except Exception as e:
            logger.error(f"Failed to validate credentials: {str(e)}")
            return False


if __name__ == "__main__":
    # spot_names = []
    # connector = HighspotConnector(spot_names)
    # credentials = {
    #     "highspot_key": "aa11f5e9e541f1641aa5",
    #     "highspot_secret": "65d9a6e7e5bd66a4540faaa787027d207ee7a7126d3078d92d1b7185c0289ee6"
    # }
    # connector.load_credentials(credentials=credentials)
    # for doc in connector.load_from_state():
    #     print(doc)

    primary_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        priority=OnyxCeleryPriority.HIGH,
    )
