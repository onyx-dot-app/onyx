import copy
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import requests
from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import DRUPAL_WIKI_ATTACHMENT_SIZE_THRESHOLD
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.drupal_wiki.models import DrupalWikiCheckpoint
from onyx.connectors.drupal_wiki.models import DrupalWikiPage
from onyx.connectors.drupal_wiki.models import DrupalWikiPageContent
from onyx.connectors.drupal_wiki.models import DrupalWikiPageResponse
from onyx.connectors.drupal_wiki.models import DrupalWikiSpace
from onyx.connectors.drupal_wiki.models import DrupalWikiSpaceResponse
from onyx.connectors.drupal_wiki.utils import build_drupal_wiki_document_id
from onyx.connectors.drupal_wiki.utils import datetime_from_timestamp
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import ConnectorFailure
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import ALL_ACCEPTED_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder
from typing_extensions import override

logger = setup_logger()

MAX_API_PAGE_SIZE = 2000  # max allowed by API

SUPPORTED_ATTACHMENT_EXTENSIONS = set(ALL_ACCEPTED_FILE_EXTENSIONS)


rate_limited_get = retry_builder()(
    rate_limit_builder(max_calls=10, period=1)(rl_requests.get)
)


class DrupalWikiConnector(
    CheckpointedConnector[DrupalWikiCheckpoint],
    SlimConnector,
):
    def __init__(
        self,
        base_url: str,
        spaces: Optional[List[str]] = None,
        pages: Optional[List[str]] = None,
        include_all_spaces: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
        continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE,
        drupal_wiki_scope: Optional[str] = None,
        include_attachments: bool = False,
        allow_images: bool = False,
    ) -> None:
        """
        Initialize the Drupal Wiki connector.

        Args:
            base_url: The base URL of the Drupal Wiki instance (e.g., https://help.drupal-wiki.com)
            spaces: List of space IDs to index. If None and include_all_spaces is False, no spaces will be indexed.
            pages: List of page IDs to index. If provided, only these specific pages will be indexed.
            include_all_spaces: If True, all spaces will be indexed regardless of the spaces parameter.
            batch_size: Number of documents to process in a batch.
            continue_on_failure: If True, continue indexing even if some documents fail.
            drupal_wiki_scope: The selected tab value from the frontend. If "all_spaces", all spaces will be indexed.
            include_attachments: If True, enable processing of page attachments including images and documents.
            allow_images: If True, enable processing of image attachments.
        """
        self.base_url = base_url.rstrip("/")
        self.spaces = spaces or []
        self.pages = pages or []

        # Determine whether to include all spaces based on the selected tab
        # If drupal_wiki_scope is "all_spaces", we should index all spaces
        # If it's "specific_spaces", we should only index the specified spaces
        # If it's None, we use the include_all_spaces parameter
        if drupal_wiki_scope == "all_spaces":
            logger.info("drupal_wiki_scope is 'all_spaces', will index all spaces")
            self.include_all_spaces = True
        elif drupal_wiki_scope == "specific_spaces":
            logger.info(
                "drupal_wiki_scope is 'specific_spaces', will only index specified spaces"
            )
            self.include_all_spaces = False
        else:
            logger.info(
                f"drupal_wiki_scope not set, using include_all_spaces={include_all_spaces}"
            )
            self.include_all_spaces = include_all_spaces

        self.batch_size = batch_size
        self.continue_on_failure = continue_on_failure

        # Attachment processing configuration
        self.include_attachments = include_attachments
        self.allow_images = allow_images

        # Will be set by load_credentials
        self.headers: Optional[Dict[str, str]] = None
        self._api_token: Optional[str] = None

    def set_allow_images(self, value: bool) -> None:
        """
        Set whether to allow image section processing.

        Args:
            value: Whether to allow image section processing.
        """
        logger.info(f"Setting allow_images to {value}.")
        self.allow_images = value

    def set_include_attachments(self, value: bool) -> None:
        """
        Set whether to allow attachment processing (text and images).

        Args:
            value: Whether to allow attachment processing.
        """
        logger.info(f"Setting include_attachments to {value}.")
        self.include_attachments = value

    def _get_page_attachments(self, page_id: int) -> List[Dict[str, Any]]:
        """
        Get all attachments for a specific page.

        Args:
            page_id: ID of the page.

        Returns:
            List of attachment dictionaries.
        """
        url = f"{self.base_url}/api/rest/scope/api/attachment"
        params = {"pageId": str(page_id)}
        logger.info(f"Fetching attachments for page {page_id} from {url}")

        try:
            response = rate_limited_get(url, headers=self.headers, params=params)
            response.raise_for_status()
            attachments = response.json()
            logger.info(f"Found {len(attachments)} attachments for page {page_id}")
            return attachments
        except Exception as e:
            logger.warning(f"Failed to fetch attachments for page {page_id}: {e}")
            return []

    def _download_attachment(self, attachment_id: int) -> bytes:
        """
        Download attachment content.

        Args:
            attachment_id: ID of the attachment to download.

        Returns:
            Raw bytes of the attachment.
        """
        url = f"{self.base_url}/api/rest/scope/api/attachment/{attachment_id}/download"
        logger.info(f"Downloading attachment {attachment_id} from {url}")

        # Use headers without Accept for binary downloads
        if self.headers is None:
            raise ValueError(
                "Headers not set in connector instance"
            )  # because mypy complains
        download_headers = {"Authorization": self.headers["Authorization"]}

        response = rate_limited_get(url, headers=download_headers)
        response.raise_for_status()

        return response.content

    def _validate_attachment_filetype(self, attachment: Dict[str, Any]) -> bool:
        """
        Validate if the attachment file type is supported.

        Args:
            attachment: Attachment dictionary from Drupal Wiki API.

        Returns:
            True if the file type is supported, False otherwise.
        """
        file_name = attachment.get("fileName", "")
        if not file_name:
            return False

        # Get file extension
        file_extension = Path(file_name).suffix.lower()

        if file_extension in SUPPORTED_ATTACHMENT_EXTENSIONS:
            return True
        logger.info(f"Unsupported file type: {file_extension} for {file_name}")
        return False

    def _get_media_type_from_filename(self, filename: str) -> str:
        """
        Get media type from filename using the standard mimetypes library.

        Args:
            filename: The filename.

        Returns:
            Media type string.
        """
        mime_type, _encoding = mimetypes.guess_type(filename)
        return mime_type or "application/octet-stream"

    def _process_attachment(
        self,
        attachment: Dict[str, Any],
        page_id: int,
        download_url: str,
    ) -> tuple[List[TextSection | ImageSection], Optional[str]]:
        """
        Process a single attachment and return generated sections.

        Args:
            attachment: Attachment dictionary from Drupal Wiki API.
            page_id: ID of the parent page.
            download_url: Direct download URL for the attachment.

        Returns:
            Tuple of (sections, error_message). If error_message is not None, the
            sections list should be treated as invalid.
        """
        sections: List[TextSection | ImageSection] = []

        try:
            if not self._validate_attachment_filetype(attachment):
                return (
                    [],
                    f"Unsupported file type: {attachment.get('fileName', 'unknown')}",
                )

            attachment_id = attachment["id"]
            file_name = attachment.get("fileName", f"attachment_{attachment_id}")
            file_size = attachment.get("fileSize", 0)
            media_type = self._get_media_type_from_filename(file_name)

            if file_size > DRUPAL_WIKI_ATTACHMENT_SIZE_THRESHOLD:
                return [], f"Attachment too large: {file_size} bytes"

            try:
                raw_bytes = self._download_attachment(attachment_id)
            except Exception as e:
                return [], f"Failed to download attachment: {e}"

            if media_type.startswith("image/"):
                if not self.allow_images:
                    logger.info(
                        "Skipping image attachment %s because allow_images is False",
                        file_name,
                    )
                    return [], None

                try:
                    image_section, _ = store_image_and_create_section(
                        image_data=raw_bytes,
                        file_id=str(attachment_id),
                        display_name=attachment.get(
                            "name", attachment.get("fileName", "Unknown")
                        ),
                        link=download_url,
                        media_type=media_type,
                        file_origin=FileOrigin.CONNECTOR,
                    )
                    sections.append(image_section)
                    logger.info("Stored image attachment with file name: %s", file_name)
                except Exception as e:
                    return [], f"Image storage failed: {e}"

                return sections, None

            image_counter = 0

            def _store_embedded_image(image_data: bytes, image_name: str) -> None:
                nonlocal image_counter

                if not self.allow_images:
                    return

                media_for_image = self._get_media_type_from_filename(image_name)
                if media_for_image == "application/octet-stream":
                    try:
                        media_for_image = get_image_type_from_bytes(image_data)
                    except ValueError:
                        logger.debug(
                            "Unable to determine media type for embedded image %s on attachment %s",
                            image_name,
                            file_name,
                        )

                image_counter += 1
                display_name = (
                    image_name
                    or f"{attachment.get('name', file_name)} - embedded image {image_counter}"
                )

                try:
                    image_section, _ = store_image_and_create_section(
                        image_data=image_data,
                        file_id=f"{attachment_id}_embedded_{image_counter}",
                        display_name=display_name,
                        link=download_url,
                        media_type=media_for_image,
                        file_origin=FileOrigin.CONNECTOR,
                    )
                    sections.append(image_section)
                except Exception as err:
                    logger.warning(
                        "Failed to store embedded image %s for attachment %s: %s",
                        image_name or image_counter,
                        file_name,
                        err,
                    )

            extraction_result = extract_text_and_images(
                file=BytesIO(raw_bytes),
                file_name=file_name,
                content_type=media_type,
                image_callback=_store_embedded_image if self.allow_images else None,
            )

            text_content = extraction_result.text_content.strip()
            if text_content:
                sections.insert(0, TextSection(text=text_content, link=download_url))
                logger.info(
                    "Extracted %d characters from %s", len(text_content), file_name
                )
            elif not sections:
                return [], f"No text extracted for {file_name}"

            return sections, None

        except Exception as e:
            logger.error(
                "Failed to process attachment %s on page %s: %s",
                attachment.get("name", "unknown"),
                page_id,
                e,
            )
            return [], f"Failed to process attachment: {e}"

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        Load credentials for the Drupal Wiki connector.

        Args:
            credentials: Dictionary containing the API token.

        Returns:
            None
        """
        if "drupal_wiki_api_token" not in credentials:
            raise ConnectorValidationError(
                "API token is required for Drupal Wiki connector"
            )

        self._api_token = credentials["drupal_wiki_api_token"]
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_token}",
        }

        return None

    def _get_spaces(self) -> List[DrupalWikiSpace]:
        """
        Get all spaces from the Drupal Wiki instance.

        Returns:
            List of DrupalWikiSpace objects.
        """
        url = f"{self.base_url}/api/rest/scope/api/space"
        size = MAX_API_PAGE_SIZE
        page = 0
        all_spaces = []
        has_more = True
        max_pages = 100  # Safety limit to prevent infinite loops

        while has_more and page < max_pages:
            params = {"size": size, "page": page}
            logger.info(f"Fetching spaces from {url} (page={page}, size={size})")
            response = rate_limited_get(url, headers=self.headers, params=params)
            response.raise_for_status()
            resp_json = response.json()
            space_response = DrupalWikiSpaceResponse.model_validate(resp_json)

            logger.info(f"Fetched {len(space_response.content)} spaces (page={page})")
            all_spaces.extend(space_response.content)

            # Continue if we got a full page, indicating there might be more
            has_more = len(space_response.content) >= size

            page += 1

        if page >= max_pages:
            logger.warning(
                f"Reached maximum page limit ({max_pages}) while fetching spaces"
            )

        logger.info(f"Total spaces fetched: {len(all_spaces)}")
        return all_spaces

    def _get_pages_for_space(
        self, space_id: int, modified_after: Optional[SecondsSinceUnixEpoch] = None
    ) -> List[DrupalWikiPage]:
        """
        Get all pages for a specific space, optionally filtered by modification time.

        Args:
            space_id: ID of the space.
            modified_after: Only return pages modified after this timestamp (seconds since Unix epoch).

        Returns:
            List of DrupalWikiPage objects.
        """
        url = f"{self.base_url}/api/rest/scope/api/page"
        size = MAX_API_PAGE_SIZE
        page = 0
        all_pages = []
        has_more = True
        max_pages = 100  # Safety limit to prevent infinite loops

        while has_more and page < max_pages:
            params: dict[str, str | int] = {
                "space": str(space_id),
                "size": size,
                "page": page,
            }

            # Add modifiedAfter parameter if provided
            if modified_after is not None:
                params["modifiedAfter"] = int(modified_after)

            logger.info(
                f"Fetching pages for space {space_id} from {url} (page={page}, size={size}, modified_after={modified_after})"
            )
            response = rate_limited_get(url, headers=self.headers, params=params)
            response.raise_for_status()
            resp_json = response.json()

            try:
                page_response = DrupalWikiPageResponse.model_validate(resp_json)
            except Exception as e:
                logger.error(f"Failed to validate Drupal Wiki page response: {e}")
                logger.debug(f"Response data: {resp_json}")
                raise ConnectorValidationError(f"Invalid API response format: {e}")

            logger.info(
                f"Fetched {len(page_response.content)} pages in space {space_id} (page={page})"
            )

            # Pydantic should automatically parse content items as DrupalWikiPage objects
            # If validation fails, it will raise an exception which we should catch
            all_pages.extend(page_response.content)

            # Continue if we got a full page, indicating there might be more
            has_more = len(page_response.content) >= size

            page += 1

        if page >= max_pages:
            logger.warning(
                f"Reached maximum page limit ({max_pages}) while fetching pages for space {space_id}"
            )

        logger.info(f"Total pages fetched for space {space_id}: {len(all_pages)}")
        return all_pages

    def _get_page_content(self, page_id: int) -> DrupalWikiPageContent:
        """
        Get the content of a specific page.

        Args:
            page_id: ID of the page.

        Returns:
            DrupalWikiPageContent object.
        """
        url = f"{self.base_url}/api/rest/scope/api/page/{page_id}"
        response = rate_limited_get(url, headers=self.headers)
        response.raise_for_status()

        return DrupalWikiPageContent.model_validate(response.json())

    def _process_page(self, page: DrupalWikiPage) -> Document | ConnectorFailure:
        """
        Process a page and convert it to a Document.

        Args:
            page: DrupalWikiPage object.

        Returns:
            Document object or ConnectorFailure.
        """
        try:
            # Get page content
            page_content = self._get_page_content(page.id)

            # Extract text from HTML
            text_content = parse_html_page_basic(page_content.body)

            # Create document URL
            page_url = build_drupal_wiki_document_id(self.base_url, page.id)

            # Create sections with just the page content
            sections: List[TextSection | ImageSection] = [
                TextSection(text=text_content, link=page_url)
            ]

            # Only process attachments if self.include_attachments is True
            if self.include_attachments:
                attachments = self._get_page_attachments(page.id)
                for attachment in attachments:
                    logger.info(
                        f"Processing attachment: {attachment.get('name', 'Unknown')} (ID: {attachment['id']})"
                    )
                    # Use downloadUrl from API; fallback to page URL
                    raw_download = attachment.get("downloadUrl")
                    if raw_download:
                        download_url = (
                            raw_download
                            if raw_download.startswith("http")
                            else f"{self.base_url.rstrip('/')}" + raw_download
                        )
                    else:
                        download_url = page_url
                    # Process the attachment
                    attachment_sections, error = self._process_attachment(
                        attachment, page.id, download_url
                    )
                    if error:
                        logger.warning(
                            "Error processing attachment %s: %s",
                            attachment.get("name", "Unknown"),
                            error,
                        )
                        continue

                    if attachment_sections:
                        sections.extend(attachment_sections)
                        logger.info(
                            "Added %d section(s) for attachment %s",
                            len(attachment_sections),
                            attachment.get("name", "Unknown"),
                        )

            # Create metadata
            metadata: Dict[str, str | List[str]] = {
                "space_id": str(page.homeSpace),
                "page_id": str(page.id),
                "type": page.type,
            }

            # Create document
            return Document(
                id=page_url,
                sections=sections,
                source=DocumentSource.DRUPAL_WIKI,
                semantic_identifier=page.title,
                metadata=metadata,
                doc_updated_at=datetime_from_timestamp(page.lastModified),
            )
        except Exception as e:
            logger.error(f"Error processing page {page.id}: {e}")
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=str(page.id),
                    document_link=build_drupal_wiki_document_id(self.base_url, page.id),
                ),
                failure_message=f"Error processing page {page.id}: {e}",
                exception=e,
            )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: DrupalWikiCheckpoint,
    ) -> CheckpointOutput[DrupalWikiCheckpoint]:
        """
        Load documents from a checkpoint.

        Args:
            start: Start time as seconds since Unix epoch.
            end: End time as seconds since Unix epoch.
            checkpoint: Checkpoint to resume from.

        Returns:
            Generator yielding documents and the updated checkpoint.
        """
        checkpoint = copy.deepcopy(checkpoint)
        logger.info(
            f"Starting load_from_checkpoint with include_all_spaces={self.include_all_spaces}, spaces={self.spaces}"
        )

        # Process specific page IDs if provided
        if self.pages:
            logger.info(f"Processing specific pages: {self.pages}")
            # Initialize the checkpoint for specific pages if needed
            if not checkpoint.is_processing_specific_pages:
                checkpoint.is_processing_specific_pages = True
                checkpoint.page_ids = [int(page_id.strip()) for page_id in self.pages]
                checkpoint.current_page_id_index = 0

            # Process pages from the checkpoint
            while checkpoint.current_page_id_index < len(checkpoint.page_ids):
                page_id = checkpoint.page_ids[checkpoint.current_page_id_index]
                logger.info(f"Processing page ID: {page_id}")

                try:
                    # Get the page content directly
                    page_content = self._get_page_content(page_id)

                    # Create a DrupalWikiPage object
                    page = DrupalWikiPage(
                        id=page_content.id,
                        title=page_content.title,
                        homeSpace=page_content.homeSpace,
                        lastModified=page_content.lastModified,
                        type=page_content.type,
                    )

                    # Skip pages outside the time range
                    if not self._is_page_in_time_range(page.lastModified, start, end):
                        logger.info(f"Skipping page {page_id} - outside time range")
                        checkpoint.current_page_id_index += 1
                        continue

                    # Process the page
                    doc_or_failure = self._process_page(page)
                    yield doc_or_failure

                except Exception as e:
                    logger.error(f"Error processing page ID {page_id}: {e}")
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=str(page_id),
                            document_link=build_drupal_wiki_document_id(
                                self.base_url, page_id
                            ),
                        ),
                        failure_message=f"Error processing page ID {page_id}: {e}",
                        exception=e,
                    )

                # Move to the next page ID
                checkpoint.current_page_id_index += 1

        # Process spaces if include_all_spaces is True or spaces are provided
        if self.include_all_spaces or self.spaces:
            logger.info("Processing spaces")
            # If include_all_spaces is True, always fetch all spaces
            if self.include_all_spaces:
                logger.info("Fetching all spaces")
                # Fetch all spaces
                all_spaces = self._get_spaces()
                checkpoint.spaces = [space.id for space in all_spaces]
                logger.info(f"Found {len(checkpoint.spaces)} spaces to process")
            # Otherwise, use provided spaces if checkpoint is empty
            elif not checkpoint.spaces:
                logger.info(f"Using provided spaces: {self.spaces}")
                # Use provided spaces
                checkpoint.spaces = [int(space_id.strip()) for space_id in self.spaces]

            # Process spaces from the checkpoint
            while checkpoint.current_space_index < len(checkpoint.spaces):
                space_id = checkpoint.spaces[checkpoint.current_space_index]
                logger.info(f"Processing space ID: {space_id}")

                # Get pages for the current space, filtered by start time if provided
                pages = self._get_pages_for_space(space_id, modified_after=start)

                # Process pages from the checkpoint
                while checkpoint.current_page_index < len(pages):
                    page = pages[checkpoint.current_page_index]
                    logger.info(f"Processing page: {page.title} (ID: {page.id})")

                    # For space-based pages, we already filtered by modifiedAfter in the API call
                    # Only need to check the end time boundary
                    if end and page.lastModified >= end:
                        logger.info(
                            f"Skipping page {page.id} - outside time range (after end)"
                        )
                        checkpoint.current_page_index += 1
                        continue

                    # Process the page
                    doc_or_failure = self._process_page(page)
                    yield doc_or_failure

                    # Move to the next page
                    checkpoint.current_page_index += 1

                # Move to the next space
                checkpoint.current_space_index += 1
                checkpoint.current_page_index = 0

        # All spaces and pages processed
        logger.info("Finished processing all spaces and pages")
        checkpoint.has_more = False
        return checkpoint

    @override
    def build_dummy_checkpoint(self) -> DrupalWikiCheckpoint:
        """
        Build a dummy checkpoint.

        Returns:
            DrupalWikiCheckpoint with default values.
        """
        return DrupalWikiCheckpoint(
            has_more=True,
            current_space_index=0,
            current_page_index=0,
            current_page_id_index=0,
            spaces=[],
            page_ids=[],
            is_processing_specific_pages=False,
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> DrupalWikiCheckpoint:
        """
        Validate a checkpoint JSON string.

        Args:
            checkpoint_json: JSON string representing a checkpoint.

        Returns:
            Validated DrupalWikiCheckpoint.
        """
        return DrupalWikiCheckpoint.model_validate_json(checkpoint_json)

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """
        Retrieve all slim documents.

        Args:
            start: Start time as seconds since Unix epoch.
            end: End time as seconds since Unix epoch.
            callback: Callback for indexing heartbeat.

        Returns:
            Generator yielding batches of SlimDocument objects.
        """
        slim_docs: List[SlimDocument] = []
        logger.info(
            f"Starting retrieve_all_slim_docs with include_all_spaces={self.include_all_spaces}, spaces={self.spaces}"
        )

        # Process specific page IDs if provided
        if self.pages:
            logger.info(f"Processing specific pages: {self.pages}")
            for page_id in self.pages:
                try:
                    # Get the page content directly
                    page_content = self._get_page_content(int(page_id.strip()))

                    # Skip pages outside the time range
                    if not self._is_page_in_time_range(
                        page_content.lastModified, start, end
                    ):
                        logger.info(f"Skipping page {page_id} - outside time range")
                        continue

                    # Create slim document for the page
                    page_url = build_drupal_wiki_document_id(
                        self.base_url, page_content.id
                    )
                    slim_docs.append(
                        SlimDocument(
                            id=page_url,
                        )
                    )
                    logger.info(f"Added slim document for page {page_content.id}")

                    # Process attachments for this page
                    attachments = self._get_page_attachments(page_content.id)
                    for attachment in attachments:
                        if self._validate_attachment_filetype(attachment):
                            attachment_url = f"{page_url}#attachment-{attachment['id']}"
                            slim_docs.append(
                                SlimDocument(
                                    id=attachment_url,
                                )
                            )
                            logger.info(
                                f"Added slim document for attachment {attachment['id']}"
                            )

                    # Yield batch if it reaches the batch size
                    if len(slim_docs) >= self.batch_size:
                        logger.info(
                            f"Yielding batch of {len(slim_docs)} slim documents"
                        )
                        yield slim_docs
                        slim_docs = []

                        if callback and callback.should_stop():
                            return
                        if callback:
                            callback.progress("retrieve_all_slim_docs", 1)

                except Exception as e:
                    logger.error(
                        f"Error processing page ID {page_id} for slim documents: {e}"
                    )

        # Process spaces if include_all_spaces is True or spaces are provided
        if self.include_all_spaces or self.spaces:
            logger.info("Processing spaces for slim documents")
            # Get spaces to process
            spaces_to_process = []
            if self.include_all_spaces:
                logger.info("Fetching all spaces for slim documents")
                # Fetch all spaces
                all_spaces = self._get_spaces()
                spaces_to_process = [space.id for space in all_spaces]
                logger.info(f"Found {len(spaces_to_process)} spaces to process")
            else:
                logger.info(f"Using provided spaces: {self.spaces}")
                # Use provided spaces
                spaces_to_process = [int(space_id.strip()) for space_id in self.spaces]

            # Process each space
            for space_id in spaces_to_process:
                logger.info(f"Processing space ID: {space_id}")
                # Get pages for the current space, filtered by start time if provided
                pages = self._get_pages_for_space(space_id, modified_after=start)

                # Process each page
                for page in pages:
                    logger.info(f"Processing page: {page.title} (ID: {page.id})")
                    # Skip pages outside the time range
                    if end and page.lastModified >= end:
                        logger.info(
                            f"Skipping page {page.id} - outside time range (after end)"
                        )
                        continue

                    # Create slim document for the page
                    page_url = build_drupal_wiki_document_id(self.base_url, page.id)
                    slim_docs.append(
                        SlimDocument(
                            id=page_url,
                        )
                    )
                    logger.info(f"Added slim document for page {page.id}")

                    # Process attachments for this page
                    attachments = self._get_page_attachments(page.id)
                    for attachment in attachments:
                        if self._validate_attachment_filetype(attachment):
                            attachment_url = f"{page_url}#attachment-{attachment['id']}"
                            slim_docs.append(
                                SlimDocument(
                                    id=attachment_url,
                                )
                            )
                            logger.info(
                                f"Added slim document for attachment {attachment['id']}"
                            )

                    # Yield batch if it reaches the batch size
                    if len(slim_docs) >= self.batch_size:
                        logger.info(
                            f"Yielding batch of {len(slim_docs)} slim documents"
                        )
                        yield slim_docs
                        slim_docs = []

                        if callback and callback.should_stop():
                            return
                        if callback:
                            callback.progress("retrieve_all_slim_docs", 1)

        # Yield remaining documents
        if slim_docs:
            logger.info(f"Yielding final batch of {len(slim_docs)} slim documents")
            yield slim_docs

    def validate_connector_settings(self) -> None:
        """
        Validate the connector settings.

        Raises:
            ConnectorValidationError: If the settings are invalid.
        """
        if not self.headers:
            raise ConnectorMissingCredentialError("Drupal Wiki")

        try:
            # Try to fetch spaces to validate the connection
            self._get_spaces()
        except requests.exceptions.RequestException as e:
            raise ConnectorValidationError(f"Failed to connect to Drupal Wiki: {e}")

    def _is_page_in_time_range(
        self,
        last_modified: int,
        start: Optional[SecondsSinceUnixEpoch],
        end: Optional[SecondsSinceUnixEpoch],
    ) -> bool:
        """
        Check if a page's last modified timestamp falls within the specified time range.

        Args:
            last_modified: The page's last modified timestamp.
            start: Start time as seconds since Unix epoch (inclusive).
            end: End time as seconds since Unix epoch (exclusive).

        Returns:
            True if the page is within the time range, False otherwise.
        """
        if start and last_modified < start:
            return False
        if end and last_modified >= end:
            return False
        return True
