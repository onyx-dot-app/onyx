from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import requests
from dateutil import parser as date_parser
from pydantic import BaseModel
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CODA_API_BASE = "https://coda.io/apis/v1"
_CODA_PAGE_SIZE = 100
_CODA_CALL_TIMEOUT = 30  # 30 seconds


class CodaObjectBase(BaseModel):
    id: str
    type: str
    href: str
    browserLink: str
    name: str


class CodaDoc(CodaObjectBase):
    """Represents a Coda Doc object"""

    owner: str
    ownerName: str
    createdAt: str
    updatedAt: str
    workspace: dict[str, Any]
    folder: dict[str, Any]
    icon: Optional[dict[str, Any]] = None
    docSize: Optional[dict[str, Any]] = None
    sourceDoc: Optional[dict[str, Any]] = None
    published: Optional[dict[str, Any]] = None


class CodaPageReference(CodaObjectBase):
    """Represents a Coda Page reference object"""


class CodaPage(CodaObjectBase):
    """Represents a Coda Page object"""

    subtitle: Optional[str] = None
    icon: Optional[dict[str, Any]] = None
    image: Optional[dict[str, Any]] = None
    contentType: str
    isHidden: bool
    createdAt: str
    updatedAt: str
    parent: CodaPageReference | None = None
    children: list[CodaPageReference]


class CodaConnector(LoadConnector, PollConnector):
    """Coda connector that reads all Coda docs and pages
    this integration has been granted access to.

    Arguments:
        batch_size (int): Number of objects to index in a batch
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        doc_ids: list[str] | None = None,
    ) -> None:
        """Initialize with parameters."""
        self.batch_size = batch_size
        self.headers = {
            "Content-Type": "application/json",
        }
        self.export_max_attempts = 10
        self.export_poll_interval = 1.0
        self.indexed_pages: set[str] = set()
        self.doc_ids = set(doc_ids) if doc_ids else None

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_docs(self, page_token: str | None = None) -> dict[str, Any]:
        """Fetch all accessible docs via the Coda API."""
        logger.debug("Fetching Coda docs")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        res = rl_requests.get(
            f"{_CODA_API_BASE}/docs",
            headers=self.headers,
            params=params,
            timeout=_CODA_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            try:
                error_body = res.json()
            except Exception:
                error_body = res.text

            logger.exception(f"Error fetching docs: {error_body}")
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_pages(
        self, doc_id: str, page_token: str | None = None
    ) -> dict[str, Any]:
        """Fetch all pages in a doc via the Coda API."""
        logger.debug(f"Fetching pages for doc '{doc_id}'")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        res = rl_requests.get(
            f"{_CODA_API_BASE}/docs/{doc_id}/pages",
            headers=self.headers,
            params=params,
            timeout=_CODA_CALL_TIMEOUT,
        )

        try:
            res.raise_for_status()
        except Exception as e:
            try:
                error_body = res.json()
            except Exception:
                error_body = res.text

            logger.exception(f"Error fetching pages for doc '{doc_id}': {error_body}")
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _export_page_content(self, doc_id: str, page_id: str) -> str | None:
        """Export page content as markdown via the Coda API.

        Returns:
            str: Page content in markdown format
            None: If export failed (API error, timeout, etc.)
        """
        logger.debug(f"Exporting content for page '{page_id}' in doc '{doc_id}'")

        # Start the export
        try:
            res = rl_requests.post(
                f"{_CODA_API_BASE}/docs/{doc_id}/pages/{page_id}/export",
                headers=self.headers,
                json={"outputFormat": "markdown"},
                timeout=_CODA_CALL_TIMEOUT,
            )
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"Error starting export for page '{page_id}': {e}")
            return None

        export_data = res.json()
        request_id = export_data.get("id")

        if not request_id:
            logger.warning(f"No request ID returned for page '{page_id}'")
            return None

        # Poll for the export result with exponential backoff
        import time

        for attempt in range(self.export_max_attempts):
            # Exponential backoff: 1s, 2s, 4s, 8s, etc.
            wait_time = self.export_poll_interval * (2**attempt)

            try:
                status_res = rl_requests.get(
                    f"{_CODA_API_BASE}/docs/{doc_id}/pages/{page_id}/export/{request_id}",
                    headers=self.headers,
                    timeout=_CODA_CALL_TIMEOUT,
                )
                status_res.raise_for_status()
            except Exception as e:
                logger.warning(
                    f"Error checking export status for page '{page_id}': {e}"
                )
                return None

            status_data = status_res.json()
            status = status_data.get("status")

            if status == "complete":
                download_link = status_data.get("downloadLink")
                if not download_link:
                    logger.warning(f"No download link for page '{page_id}'")
                    return None

                try:
                    content_res = rl_requests.get(
                        download_link,
                        timeout=_CODA_CALL_TIMEOUT,
                    )
                    content_res.raise_for_status()
                    content = content_res.text

                    # Validate content is not empty
                    if not content.strip():
                        logger.debug(
                            f"Page '{page_id}' exported but contains no content"
                        )
                        return ""

                    logger.debug(
                        f"Successfully exported page '{page_id}' ({len(content)} chars)"
                    )
                    return content
                except Exception as e:
                    logger.warning(
                        f"Error downloading content for page '{page_id}': {e}"
                    )
                    return None

            elif status == "failed":
                logger.warning(f"Export failed for page '{page_id}'")
                return None

            elif status == "in_progress":
                # Only log on first attempt to avoid spam
                if attempt == 0:
                    logger.debug(f"Export in progress for page '{page_id}'")

                # Wait before polling again (exponential backoff)
                if attempt < self.export_max_attempts - 1:
                    time.sleep(wait_time)

            else:
                logger.warning(f"Unknown export status '{status}' for page '{page_id}'")
                return None

        logger.warning(
            f"Export timed out for page '{page_id}' after {self.export_max_attempts} attempts"
        )
        return None

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Robustly parse ISO 8601 timestamps."""
        dt = date_parser.isoparse(timestamp_str)
        return dt.astimezone(timezone.utc)

    def _get_page_path(self, page: CodaPage, page_map: dict[str, CodaPage]) -> str:
        """Constructs the breadcrumb path for a page."""
        path_parts = [page.name]
        current_page = page
        while current_page.parent:
            parent_id = current_page.parent.id
            if not parent_id or parent_id not in page_map:
                break
            current_page = page_map[parent_id]
            path_parts.append(current_page.name)

        return " / ".join(reversed(path_parts))

    def _read_pages(
        self, doc: CodaDoc, pages: list[CodaPage], page_map: dict[str, CodaPage]
    ) -> Generator[Document, None, None]:
        """Reads pages and generates Documents"""
        for page in pages:
            if page.isHidden:
                logger.debug(f"Skipping hidden page '{page.name}'.")
                continue

            page_key = f"{doc.id}:{page.id}"
            if page_key in self.indexed_pages:
                logger.debug(f"Already indexed page '{page.name}'. Skipping.")
                continue

            logger.info(f"Reading page '{page.name}' in doc '{doc.name}'")

            # Get page content
            content = self._export_page_content(doc.id, page.id)
            if content is None:
                logger.warning(f"Skipping page {page.id}: export failed")
                continue

            if not content.strip():
                logger.debug(f"Skipping page '{page.name}': no content")
                continue

            page_title = page.name or f"Untitled Page {page.id}"

            # Mark as indexed
            self.indexed_pages.add(page_key)

            # Create document title
            if page.subtitle:
                page_title = f"{page_title} - {page.subtitle}"

            # Build the text content
            text = f"{page_title}\n\n{content}"

            # Build metadata
            metadata: dict[str, str | list[str]] = {
                "doc_name": doc.name,
                "doc_id": doc.id,
                "page_id": page.id,
                "path": self._get_page_path(page, page_map),
            }

            if page.parent:
                metadata["parent_page_id"] = page.parent.id

            if page.icon:
                metadata["icon"] = str(page.icon)

            sections: list[TextSection | ImageSection] = [
                TextSection(
                    link=page.browserLink,
                    text=text,
                )
            ]

            yield Document(
                id=page_key,
                sections=sections,
                source=DocumentSource.CODA,
                semantic_identifier=page_title,
                doc_updated_at=self._parse_timestamp(
                    page.updatedAt.replace("Z", "+00:00")
                ),
                metadata=metadata,
            )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Applies API token to headers"""
        self.headers["Authorization"] = f'Bearer {credentials["coda_api_token"]}'
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Loads all doc and page data from a Coda workspace.

        Returns:
            list[Document]: list of documents.
        """
        logger.info("Starting full load of Coda docs and pages")

        next_docs_page_token = None
        while True:
            docs_response = self._fetch_docs(next_docs_page_token)
            docs = [CodaDoc(**doc) for doc in docs_response.get("items", [])]

            # Filter by doc_ids if specified
            if self.doc_ids:
                docs = [doc for doc in docs if doc.id in self.doc_ids]

            for doc in docs:
                logger.info(f"Processing doc: {doc.name}")

                # Fetch all pages for this doc to build hierarchy
                all_pages: list[CodaPage] = []
                next_page_token = None
                while True:
                    pages_response = self._fetch_pages(doc.id, next_page_token)
                    all_pages.extend(
                        [CodaPage(**page) for page in pages_response.get("items", [])]
                    )

                    next_page_token = pages_response.get("nextPageToken")
                    if not next_page_token:
                        break

                # Build map for hierarchy
                page_map = {p.id: p for p in all_pages}

                # Generate documents from pages
                yield from batch_generator(
                    self._read_pages(doc, all_pages, page_map), self.batch_size
                )

            # Check for more docs
            next_docs_page_token = docs_response.get("nextPageToken")
            if not next_docs_page_token:
                break

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Uses the Coda API to fetch updated docs and pages
        within a time period.
        """
        logger.info(f"Polling Coda for updates between {start} and {end}")

        # Fetch all docs
        page_token = None
        while True:
            docs_response = self._fetch_docs(page_token)
            docs = [CodaDoc(**doc) for doc in docs_response.get("items", [])]

            for doc in docs:
                # Check if doc was updated in the time range
                doc_updated_at = self._parse_timestamp(doc.updatedAt)

                if (
                    doc_updated_at.timestamp() < start
                    or doc_updated_at.timestamp() > end
                ):
                    continue

                logger.info(f"Processing updated doc: {doc.name}")

                # Fetch all pages for this doc to build hierarchy
                # We need all pages even if we only index some, to build the full path
                all_pages: list[CodaPage] = []
                page_page_token = None
                while True:
                    pages_response = self._fetch_pages(doc.id, page_page_token)
                    all_pages.extend(
                        [CodaPage(**page) for page in pages_response.get("items", [])]
                    )

                    page_page_token = pages_response.get("nextPageToken")
                    if not page_page_token:
                        break

                page_map = {p.id: p for p in all_pages}

                # Filter pages by update time
                updated_pages = []
                for page in all_pages:
                    page_updated_at = datetime.fromisoformat(
                        page.updatedAt.replace("Z", "+00:00")
                    ).timestamp()
                    if start < page_updated_at <= end:
                        updated_pages.append(page)

                if updated_pages:
                    # Generate documents from updated pages
                    yield from batch_generator(
                        self._read_pages(doc, updated_pages, page_map), self.batch_size
                    )

            # Check for more docs
            page_token = docs_response.get("nextPageToken")
            if not page_token:
                break

    def validate_connector_settings(self) -> None:
        if not self.headers.get("Authorization"):
            raise ConnectorMissingCredentialError("Coda credentials not loaded.")

        try:
            res = rl_requests.get(
                f"{_CODA_API_BASE}/whoami",
                headers=self.headers,
                timeout=_CODA_CALL_TIMEOUT,
            )
            res.raise_for_status()

        except requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if http_err.response else None

            if status_code == 401:
                raise CredentialExpiredError(
                    "Coda credential appears to be invalid or expired (HTTP 401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your Coda token does not have sufficient permissions (HTTP 403)."
                )
            elif status_code == 429:
                raise ConnectorValidationError(
                    "Validation failed due to Coda rate-limits being exceeded (HTTP 429). "
                    "Please try again later."
                )
            else:
                raise UnexpectedValidationError(
                    f"Unexpected Coda HTTP error (status={status_code}): {http_err}"
                ) from http_err

        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during Coda settings validation: {exc}"
            )


if __name__ == "__main__":
    import os

    connector = CodaConnector(
        doc_ids=(
            os.environ.get("CODA_DOC_IDS", "").split(",")
            if os.environ.get("CODA_DOC_IDS")
            else None
        )
    )
    connector.load_credentials({"coda_api_token": os.environ.get("CODA_API_TOKEN")})
    connector.validate_connector_settings()
    print("Coda connector validation successful!")
