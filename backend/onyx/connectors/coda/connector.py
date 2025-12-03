from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from time import sleep
from typing import Any

import requests
from dateutil import parser as date_parser
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table import CodaColumn
from onyx.connectors.coda.models.table import CodaRow
from onyx.connectors.coda.models.table import CodaTableReference
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
        max_table_rows: int = 1000,
        include_tables: bool = True,
    ) -> None:
        """Initialize with parameters."""
        self.batch_size = batch_size
        self.headers = {
            "Content-Type": "application/json",
        }
        self.export_max_attempts = 10
        self.export_poll_interval = 1.0
        self.indexed_pages: set[str] = set()
        self.indexed_tables: set[str] = set()
        self.doc_ids = set(doc_ids) if doc_ids else None
        self.max_table_rows = max_table_rows
        self.include_tables = include_tables

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
    def _fetch_tables(
        self, doc_id: str, page_token: str | None = None
    ) -> dict[str, Any]:
        """Fetch all tables in a doc via the Coda API."""
        logger.debug(f"Fetching tables for doc '{doc_id}'")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        res = rl_requests.get(
            f"{_CODA_API_BASE}/docs/{doc_id}/tables",
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

            logger.exception(f"Error fetching tables for doc '{doc_id}': {error_body}")
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_table_columns(self, doc_id: str, table_id: str) -> dict[str, Any]:
        """Fetch column definitions for a table via the Coda API."""
        logger.debug(f"Fetching columns for table '{table_id}' in doc '{doc_id}'")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}

        res = rl_requests.get(
            f"{_CODA_API_BASE}/docs/{doc_id}/tables/{table_id}/columns",
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

            logger.exception(
                f"Error fetching columns for table '{table_id}': {error_body}"
            )
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_table_rows(
        self,
        doc_id: str,
        table_id: str,
        page_token: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Fetch rows from a table via the Coda API."""
        logger.debug(f"Fetching rows for table '{table_id}' in doc '{doc_id}'")
        params: dict[str, Any] = {
            "limit": limit or _CODA_PAGE_SIZE,
            "useColumnNames": False,
        }
        if page_token:
            params["pageToken"] = page_token

        res = rl_requests.get(
            f"{_CODA_API_BASE}/docs/{doc_id}/tables/{table_id}/rows",
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

            logger.exception(
                f"Error fetching rows for table '{table_id}': {error_body}"
            )
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
                        return None

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

            elif status == "inProgress":
                # Only log on first attempt to avoid spam
                if attempt == 0:
                    logger.debug(f"Export in progress for page '{page_id}'")

                # Wait before polling again (exponential backoff)
                if attempt < self.export_max_attempts - 1:
                    sleep(wait_time)

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

    def _format_cell_value(self, value: Any) -> str:
        """Format a cell value for markdown table display."""
        if value is None or value == "":
            return ""

        # Handle different value types
        if isinstance(value, dict):
            # Handle special Coda value types
            if "name" in value:
                return str(value["name"])
            elif "url" in value:
                return str(value["url"])
            else:
                return str(value)
        elif isinstance(value, list):
            # Join list items
            return ", ".join(str(item) for item in value)
        elif isinstance(value, bool):
            return "✓" if value else ""
        else:
            # Escape pipe characters for markdown tables
            return str(value).replace("|", "\\|").replace("\n", " ")

    def _convert_table_to_markdown(
        self,
        table: CodaTableReference,
        columns: list[CodaColumn],
        rows: list[CodaRow],
    ) -> str:
        """Convert table data to markdown format.

        Args:
            table: The table metadata
            columns: List of column definitions
            rows: List of row data (may be truncated)

        Returns:
            Markdown formatted table string
        """
        if not columns:
            return f"# {table.name}\n\n*Empty table - no columns defined*"

        if not rows:
            return f"# {table.name}\n\n*Empty table - no data*"

        # Build column name to ID mapping
        col_id_to_name = {col.id: col.name for col in columns if col.display}

        if not col_id_to_name:
            return f"# {table.name}\n\n*No displayable columns*"

        # Build markdown table
        lines = [f"# {table.name}\n"]

        # Add row count info if truncated
        # if len(rows) < table.rowCount:
        #     lines.append(f"*Showing {len(rows)} of {table.rowCount} rows*\n")

        # Header row
        header_cells = [col_id_to_name[col_id] for col_id in col_id_to_name.keys()]
        lines.append("| " + " | ".join(header_cells) + " |")

        # Separator row
        lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")

        # Data rows
        for row in rows:
            cells = []
            for col_id in col_id_to_name.keys():
                value = row.values.get(col_id, "")
                cells.append(self._format_cell_value(value))
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    def _read_tables(
        self, doc: CodaDoc, tables: list[CodaTableReference]
    ) -> Generator[Document, None, None]:
        """Reads tables and generates Documents"""
        for table in tables:
            table_key = f"{doc.id}:table:{table.id}"
            if table_key in self.indexed_tables:
                logger.debug(f"Already indexed table '{table.name}'. Skipping.")
                continue

            logger.info(f"Reading table '{table.name}' in doc '{doc.name}'")

            try:
                # Fetch columns
                columns_response = self._fetch_table_columns(doc.id, table.id)
                columns = [
                    CodaColumn(**col) for col in columns_response.get("items", [])
                ]

                if not columns:
                    logger.debug(f"Skipping table '{table.name}': no columns")
                    continue

                # Fetch rows (with limit)
                all_rows: list[CodaRow] = []
                next_page_token = None
                rows_fetched = 0

                while rows_fetched < self.max_table_rows:
                    remaining = self.max_table_rows - rows_fetched
                    limit = min(remaining, _CODA_PAGE_SIZE)

                    rows_response = self._fetch_table_rows(
                        doc.id, table.id, next_page_token, limit
                    )

                    batch_rows = [
                        CodaRow(**row) for row in rows_response.get("items", [])
                    ]

                    if not batch_rows:
                        break

                    all_rows.extend(batch_rows)
                    rows_fetched += len(batch_rows)

                    next_page_token = rows_response.get("nextPageToken")
                    if not next_page_token:
                        break

                if not all_rows:
                    logger.debug(f"Skipping table '{table.name}': no rows")
                    continue

                # Convert to markdown
                content = self._convert_table_to_markdown(table, columns, all_rows)

                # Mark as indexed
                self.indexed_tables.add(table_key)

                # Build metadata
                metadata: dict[str, str | list[str]] = {
                    "doc_name": doc.name,
                    "doc_id": doc.id,
                    "table_id": table.id,
                    "table_name": table.name,
                    "row_count": str(len(all_rows)),
                    "column_count": str(len(columns)),
                }

                sections: list[TextSection | ImageSection] = [
                    TextSection(
                        link=table.browserLink,
                        text=content,
                    )
                ]

                yield Document(
                    id=table_key,
                    sections=sections,
                    source=DocumentSource.CODA,
                    semantic_identifier=f"{doc.name} - {table.name}",
                    doc_updated_at=self._parse_timestamp(
                        doc.updatedAt.replace("Z", "+00:00")
                    ),
                    metadata=metadata,
                )

            except Exception as e:
                logger.warning(
                    f"Error processing table '{table.name}' in doc '{doc.name}': {e}"
                )
                continue

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
                doc_updated_at=(
                    self._parse_timestamp(page.updatedAt.replace("Z", "+00:00"))
                    if page.updatedAt
                    else None
                ),
                metadata=metadata,
            )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Applies API token to headers"""
        self.headers["Authorization"] = f'Bearer {credentials["coda_api_token"]}'
        return None

    def _load_all_documents(self) -> Generator[Document, None, None]:
        """Generator that yields all documents from Coda workspace."""
        logger.info("Starting full load of Coda docs and pages")

        next_docs_page_token = None
        while True:
            docs_response = self._fetch_docs(next_docs_page_token)
            docs = [CodaDoc(**doc) for doc in docs_response.get("items", [])]

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
                yield from self._read_pages(doc, all_pages, page_map)

                # Process tables if enabled
                if self.include_tables:
                    all_tables: list[CodaTableReference] = []
                    next_table_token = None
                    while True:
                        tables_response = self._fetch_tables(doc.id, next_table_token)
                        all_tables.extend(
                            [
                                CodaTableReference(**t)
                                for t in tables_response.get("items", [])
                            ]
                        )

                        next_table_token = tables_response.get("nextPageToken")
                        if not next_table_token:
                            break

                    if all_tables:
                        yield from self._read_tables(doc, all_tables)

            # Check for more docs
            next_docs_page_token = docs_response.get("nextPageToken")
            if not next_docs_page_token:
                break

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Loads all doc and page data from a Coda workspace.

        Returns:
            list[Document]: list of documents.
        """
        yield from batch_generator(self._load_all_documents(), self.batch_size)

    def _load_updated_documents(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[Document, None, None]:
        """Generator that yields updated documents from Coda workspace."""
        logger.info(f"Polling Coda for updates between {start} and {end}")

        # Fetch all docs
        next_docs_page_token = None
        while True:
            docs_response = self._fetch_docs(next_docs_page_token)
            docs = [CodaDoc(**doc) for doc in docs_response.get("items", [])]

            # Filter by doc_ids if specified
            if self.doc_ids:
                docs = [doc for doc in docs if doc.id in self.doc_ids]

            for doc in docs:
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
                next_pages_page_token = None
                while True:
                    pages_response = self._fetch_pages(doc.id, next_pages_page_token)
                    all_pages.extend(
                        [CodaPage(**page) for page in pages_response.get("items", [])]
                    )

                    next_pages_page_token = pages_response.get("nextPageToken")
                    if not next_pages_page_token:
                        break

                page_map = {p.id: p for p in all_pages}

                # Filter pages by update time
                updated_pages = []
                for page in all_pages:
                    if not page.updatedAt:
                        continue
                    page_updated_at = self._parse_timestamp(page.updatedAt)
                    if start < page_updated_at.timestamp() < end:
                        updated_pages.append(page)

                if updated_pages:
                    # Generate documents from updated pages
                    yield from self._read_pages(doc, updated_pages, page_map)

                # Process tables for updated docs if enabled
                # Since tables don't have individual timestamps, we re-index all tables
                # for any doc that has been updated
                if self.include_tables:
                    all_tables: list[CodaTableReference] = []
                    next_table_token = None
                    while True:
                        tables_response = self._fetch_tables(doc.id, next_table_token)
                        all_tables.extend(
                            [
                                CodaTableReference(**t)
                                for t in tables_response.get("items", [])
                            ]
                        )

                        next_table_token = tables_response.get("nextPageToken")
                        if not next_table_token:
                            break

                    if all_tables:
                        yield from self._read_tables(doc, all_tables)

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
        yield from batch_generator(
            self._load_updated_documents(start, end), self.batch_size
        )

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
