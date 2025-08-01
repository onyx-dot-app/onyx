import html
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.bookstack.client import BookStackApiClient
from onyx.connectors.bookstack.client import BookStackClientRequestFailedError
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
from onyx.file_processing.html_utils import parse_html_page_basic

# <<<<<<< n-4t
# import base64
# import logging
# =======
# ##############################################################################################
import base64
import logging
#import re
#from bs4 import BeautifulSoup
# >>>>>>> main
from io import BytesIO
from onyx.file_processing.extract_file_text import extract_text_and_images, ExtractionResult

logger = logging.getLogger(__name__)
# <<<<<<< n-4t
# =======
# ##############################################################################################
# >>>>>>> main

class BookstackConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.bookstack_client: BookStackApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.bookstack_client = BookStackApiClient(
            base_url=credentials["bookstack_base_url"],
            token_id=credentials["bookstack_api_token_id"],
            token_secret=credentials["bookstack_api_token_secret"],
        )
        return None

    @staticmethod
    def _get_doc_batch(
        batch_size: int,
        bookstack_client: BookStackApiClient,
        endpoint: str,
        transformer: Callable[[BookStackApiClient, dict], Document],
        start_ind: int,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> tuple[list[Document], int]:
        params = {
            "count": str(batch_size),
            "offset": str(start_ind),
            "sort": "+id",
        }

        if start:
            params["filter[updated_at:gte]"] = datetime.utcfromtimestamp(
                start
            ).strftime("%Y-%m-%d %H:%M:%S")

        if end:
            params["filter[updated_at:lte]"] = datetime.utcfromtimestamp(end).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        batch = bookstack_client.get(endpoint, params=params).get("data", [])
        doc_batch = [transformer(bookstack_client, item) for item in batch]

        return doc_batch, len(batch)

    @staticmethod
    def _book_to_document(
        bookstack_client: BookStackApiClient, book: dict[str, Any]
    ) -> Document:
        url = bookstack_client.build_app_url("/books/" + str(book.get("slug")))
        title = str(book.get("name", ""))
        text = book.get("name", "") + "\n" + book.get("description", "")
        updated_at_str = (
            str(book.get("updated_at")) if book.get("updated_at") is not None else None
        )
        return Document(
            id="book__" + str(book.get("id")),
            sections=[TextSection(link=url, text=text)],
            source=DocumentSource.BOOKSTACK,
            semantic_identifier="Book: " + title,
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={"type": "book"},
        )

    @staticmethod
    def _chapter_to_document(
        bookstack_client: BookStackApiClient, chapter: dict[str, Any]
    ) -> Document:
        url = bookstack_client.build_app_url(
            "/books/"
            + str(chapter.get("book_slug"))
            + "/chapter/"
            + str(chapter.get("slug"))
        )
        title = str(chapter.get("name", ""))
        text = chapter.get("name", "") + "\n" + chapter.get("description", "")
        updated_at_str = (
            str(chapter.get("updated_at"))
            if chapter.get("updated_at") is not None
            else None
        )
        return Document(
            id="chapter__" + str(chapter.get("id")),
            sections=[TextSection(link=url, text=text)],
            source=DocumentSource.BOOKSTACK,
            semantic_identifier="Chapter: " + title,
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={"type": "chapter"},
        )

    @staticmethod
    def _shelf_to_document(
        bookstack_client: BookStackApiClient, shelf: dict[str, Any]
    ) -> Document:
        url = bookstack_client.build_app_url("/shelves/" + str(shelf.get("slug")))
        title = str(shelf.get("name", ""))
        text = shelf.get("name", "") + "\n" + shelf.get("description", "")
        updated_at_str = (
            str(shelf.get("updated_at"))
            if shelf.get("updated_at") is not None
            else None
        )
        return Document(
            id="shelf:" + str(shelf.get("id")),
            sections=[TextSection(link=url, text=text)],
            source=DocumentSource.BOOKSTACK,
            semantic_identifier="Shelf: " + title,
            title=title,
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={"type": "shelf"},
        )

    @staticmethod
    def _page_to_document(
        bookstack_client: BookStackApiClient, page: dict[str, Any]
    ) -> Document:
        page_id = str(page.get("id"))
        title = str(page.get("name", ""))
        page_data = bookstack_client.get(f"/pages/{page_id}", {})
        url = bookstack_client.build_app_url(
            "/books/"
            + str(page.get("book_slug"))
            + "/page/"
            + str(page_data.get("slug"))
        )
        page_html = "<h1>" + html.escape(title) + "</h1>" + str(page_data.get("html"))
        text = parse_html_page_basic(page_html)

        attachment_sections = []
        try:
            # Get all attachments - we need to filter by page ID later
            all_attachments = bookstack_client.get("/attachments", {"filter[uploaded_to]": page_id}).get("data", [])
            for attachment in all_attachments:
                attachment_id = str(attachment.get("id"))
                try:
                    # Get full attachment details
                    attachment_details = bookstack_client.get(f"/attachments/{attachment_id}", {})
                    attachment_name = attachment_details.get("name", "Unnamed Attachment")
                    is_external = attachment_details.get("external", False)
                    content = attachment_details.get("content", "")
                    extension = attachment_details.get("extension", "")

                    # Determine filename
                    file_name = attachment_name
                    if extension and not file_name.endswith(f".{extension}"):
                        file_name += f".{extension}"
                    # Build BookStack URL for this attachment
                    attachment_url = bookstack_client.build_app_url(f"/attachments/{attachment_id}")
                    if is_external:
                        # External link (like SharePoint)
                        link_url = content
                        attachment_sections.append(TextSection(
                            link=attachment_url,
                            text=f"EXTERNAL ATTACHMENT: {file_name}\nLink: {link_url}"
                        ))
                    else:

                        # File attachment with base64 content
                        if not content:
                            logger.warning(f"No content for attachment {attachment_id}")
                            continue
                        
                        try:
                            file_bytes = base64.b64decode(content)
                        except Exception as decode_error:
                            logger.error(f"Failed to decode attachment {attachment_id}: {str(decode_error)}")
                            continue
                        
                        # Process the file content
                        file_content = BytesIO(file_bytes)
                        extraction_result = extract_text_and_images(
                            file=file_content,
                            file_name=file_name
                        )
                        
                        if extraction_result.text_content:
                            attachment_sections.append(TextSection(
                                link=attachment_url,
                                text=f"ATTACHMENT: {file_name}\n\n{extraction_result.text_content}"
                            ))
                        else:
                            logger.warning(f"Failed to extract text from attachment: {file_name}")
                except Exception as attachment_error:
                    logger.error(f"Error processing attachment {attachment_id}: {str(attachment_error)}")
        except Exception as e:
            logger.error(f"Error getting attachments for page {page_id}: {str(e)}")
        
        updated_at_str = (
            str(page_data.get("updated_at"))
            if page_data.get("updated_at") is not None
            else None
        )
        time.sleep(0.1)
        
        # Combine page content with attachments
        all_sections = [TextSection(link=url, text=text)] + attachment_sections
        
        return Document(
            id="page:" + page_id,
            sections=all_sections,
            source=DocumentSource.BOOKSTACK,
            semantic_identifier="Page: " + str(title),
            title=str(title),
            doc_updated_at=(
                time_str_to_utc(updated_at_str) if updated_at_str is not None else None
            ),
            metadata={"type": "page"},
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.bookstack_client is None:
            raise ConnectorMissingCredentialError("Bookstack")

        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.bookstack_client is None:
            raise ConnectorMissingCredentialError("Bookstack")

        transform_by_endpoint: dict[
            str, Callable[[BookStackApiClient, dict], Document]
        ] = {
            "/books": self._book_to_document,
            "/chapters": self._chapter_to_document,
            "/shelves": self._shelf_to_document,
            "/pages": self._page_to_document,
        }

        for endpoint, transform in transform_by_endpoint.items():
            start_ind = 0
            while True:
                doc_batch, num_results = self._get_doc_batch(
                    batch_size=self.batch_size,
                    bookstack_client=self.bookstack_client,
                    endpoint=endpoint,
                    transformer=transform,
                    start_ind=start_ind,
                    start=start,
                    end=end,
                )
                start_ind += num_results
                if doc_batch:
                    yield doc_batch

                if num_results < self.batch_size:
                    break
                else:
                    time.sleep(0.2)

    def validate_connector_settings(self) -> None:
        """
        Validate that the BookStack credentials and connector settings are correct.
        Specifically checks that we can make an authenticated request to BookStack.
        """
        if not self.bookstack_client:
            raise ConnectorMissingCredentialError(
                "BookStack credentials have not been loaded."
            )

        try:
            # Attempt to fetch a small batch of books (arbitrary endpoint) to verify credentials
            _ = self.bookstack_client.get(
                "/books", params={"count": "1", "offset": "0"}
            )

        except BookStackClientRequestFailedError as e:
            # Check for HTTP status codes
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "Your BookStack credentials appear to be invalid or expired (HTTP 401)."
                ) from e
            elif e.status_code == 403:
                raise InsufficientPermissionsError(
                    "The configured BookStack token does not have sufficient permissions (HTTP 403)."
                ) from e
            else:
                raise ConnectorValidationError(
                    f"Unexpected BookStack error (status={e.status_code}): {e}"
                ) from e

        except Exception as exc:
            raise ConnectorValidationError(
                f"Unexpected error while validating BookStack connector settings: {exc}"
            ) from exc
