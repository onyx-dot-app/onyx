"""Coda.io Connector for Onyx

This connector allows importing documents, pages, and tables from Coda.io
into Onyx for indexing and search.

Coda.io API Reference: https://coda.io/developers/apis/v1
"""

from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

CODA_API_BASE = "https://coda.io/apis/v1"


class CodaClientNotSetUpError(PermissionError):
    def __init__(self) -> None:
        super().__init__("Coda Client is not set up, was load_credentials called?")


class CodaConnector(LoadConnector):
    """Connector for importing documents from Coda.io.

    Supports importing:
    - Docs (workspaces/documents)
    - Pages within docs
    - Tables and their rows (as structured content)
    """

    def __init__(
        self,
        doc_id: str | None = None,
        include_tables: bool = True,
        include_pages: bool = True,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        """Initialize a CodaConnector.

        Args:
            doc_id: Optional specific Coda doc ID to import. If None, imports all accessible docs.
            include_tables: Whether to include table data from docs.
            include_pages: Whether to include page content from docs.
            batch_size: Number of documents to yield per batch.
        """
        self.doc_id = doc_id
        self.include_tables = include_tables
        self.include_pages = include_pages
        self.batch_size = batch_size
        self._api_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Coda API credentials.

        Expected credentials format:
        {
            "coda_api_token": "your-api-token"
        }
        """
        self._api_token = credentials.get("coda_api_token")
        if not self._api_token:
            raise ValueError("coda_api_token is required in credentials")
        return None

    @property
    def api_token(self) -> str:
        if not self._api_token:
            raise CodaClientNotSetUpError()
        return self._api_token

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    @retry(tries=3, delay=1, backoff=2)
    def _make_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to the Coda API with retry logic."""
        url = f"{CODA_API_BASE}/{endpoint}"
        response = requests.get(url, headers=self._get_headers(), params=params)
        response.raise_for_status()
        return response.json()

    def _list_docs(self) -> list[dict[str, Any]]:
        """List all accessible Coda docs."""
        docs = []
        page_token = None

        while True:
            params: dict[str, Any] = {"limit": 100}
            if page_token:
                params["pageToken"] = page_token

            result = self._make_request("docs", params)
            docs.extend(result.get("items", []))

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return docs

    def _get_doc(self, doc_id: str) -> dict[str, Any]:
        """Get a specific Coda doc by ID."""
        return self._make_request(f"docs/{doc_id}")

    def _list_pages(self, doc_id: str) -> list[dict[str, Any]]:
        """List all pages in a Coda doc."""
        pages = []
        page_token = None

        while True:
            params: dict[str, Any] = {"limit": 100}
            if page_token:
                params["pageToken"] = page_token

            result = self._make_request(f"docs/{doc_id}/pages", params)
            pages.extend(result.get("items", []))

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return pages

    def _get_page_content(self, doc_id: str, page_id: str) -> str:
        """Get the content of a page as text."""
        try:
            result = self._make_request(
                f"docs/{doc_id}/pages/{page_id}",
                params={"outputFormat": "markdown"},
            )
            return result.get("contentMd", "") or result.get("content", "")
        except Exception as e:
            logger.warning(f"Failed to get page content for {page_id}: {e}")
            return ""

    def _list_tables(self, doc_id: str) -> list[dict[str, Any]]:
        """List all tables in a Coda doc."""
        tables = []
        page_token = None

        while True:
            params: dict[str, Any] = {"limit": 100}
            if page_token:
                params["pageToken"] = page_token

            result = self._make_request(f"docs/{doc_id}/tables", params)
            tables.extend(result.get("items", []))

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return tables

    def _get_table_rows(
        self,
        doc_id: str,
        table_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Get rows from a table."""
        rows = []
        page_token = None

        while True:
            params: dict[str, Any] = {
                "limit": min(limit, 500),
                "useColumnNames": True,
            }
            if page_token:
                params["pageToken"] = page_token

            result = self._make_request(f"docs/{doc_id}/tables/{table_id}/rows", params)
            rows.extend(result.get("items", []))

            page_token = result.get("nextPageToken")
            if not page_token or len(rows) >= limit:
                break

        return rows[:limit]

    def _table_to_text(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
    ) -> str:
        """Convert table rows to a readable text format."""
        if not rows:
            return f"Table: {table_name}\n(empty table)"

        lines = [f"Table: {table_name}"]
        lines.append("-" * 40)

        for row in rows:
            values = row.get("values", {})
            row_lines = []
            for col_name, value in values.items():
                if value is not None and value != "":
                    row_lines.append(f"  {col_name}: {value}")
            if row_lines:
                lines.append("\n".join(row_lines))
                lines.append("")

        return "\n".join(lines)

    def _process_doc(self, doc: dict[str, Any]) -> list[Document]:
        """Process a single Coda doc and return Documents."""
        documents = []
        doc_id = doc["id"]
        doc_name = doc.get("name", "Untitled")
        doc_url = doc.get("browserLink", f"https://coda.io/d/{doc_id}")

        # Get doc metadata
        folder_name = doc.get("folder", {}).get("name", "")
        owner_name = doc.get("owner", {}).get("name", "")
        created_at = doc.get("createdAt")
        updated_at = doc.get("updatedAt")

        # Parse timestamps
        doc_updated_at = None
        if updated_at:
            try:
                doc_updated_at = datetime.fromisoformat(
                    updated_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Collect all content sections
        sections = []
        metadata: dict[str, str | list[str]] = {
            "source": "coda",
            "doc_name": doc_name,
        }
        if folder_name:
            metadata["folder"] = folder_name
        if owner_name:
            metadata["owner"] = owner_name

        # Process pages
        if self.include_pages:
            try:
                pages = self._list_pages(doc_id)
                for page in pages:
                    page_id = page["id"]
                    page_name = page.get("name", "")
                    page_content = self._get_page_content(doc_id, page_id)

                    if page_content.strip():
                        section_text = f"# {page_name}\n\n{page_content}"
                        page_url = f"{doc_url}#_lu{page_id}"
                        sections.append(
                            TextSection(
                                text=section_text,
                                link=page_url,
                            )
                        )
            except Exception as e:
                logger.warning(f"Failed to process pages for doc {doc_id}: {e}")

        # Process tables
        if self.include_tables:
            try:
                tables = self._list_tables(doc_id)
                for table in tables:
                    table_id = table["id"]
                    table_name = table.get("name", "Untitled Table")

                    try:
                        rows = self._get_table_rows(doc_id, table_id)
                        if rows:
                            table_text = self._table_to_text(table_name, rows)
                            table_url = f"{doc_url}#_tbl{table_id}"
                            sections.append(
                                TextSection(
                                    text=table_text,
                                    link=table_url,
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to get rows for table {table_id}: {e}"
                        )
            except Exception as e:
                logger.warning(f"Failed to process tables for doc {doc_id}: {e}")

        # Create document if we have content
        if sections:
            documents.append(
                Document(
                    id=f"coda_{doc_id}",
                    source=DocumentSource.CODA,
                    semantic_identifier=doc_name,
                    doc_updated_at=doc_updated_at,
                    sections=sections,
                    metadata=metadata,
                )
            )

        return documents

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load documents from Coda.io.

        Yields batches of Document objects.
        """
        logger.info("Starting Coda.io document import")

        # Get docs to process
        if self.doc_id:
            # Single doc mode
            try:
                doc = self._get_doc(self.doc_id)
                docs = [doc]
            except Exception as e:
                logger.error(f"Failed to get doc {self.doc_id}: {e}")
                return
        else:
            # All docs mode
            try:
                docs = self._list_docs()
            except Exception as e:
                logger.error(f"Failed to list Coda docs: {e}")
                return

        logger.info(f"Found {len(docs)} Coda doc(s) to process")

        # Process docs and yield in batches
        batch: list[Document] = []
        for doc in docs:
            try:
                documents = self._process_doc(doc)
                batch.extend(documents)

                while len(batch) >= self.batch_size:
                    yield batch[: self.batch_size]
                    batch = batch[self.batch_size :]

            except Exception as e:
                logger.error(f"Failed to process doc {doc.get('id')}: {e}")
                continue

        # Yield remaining documents
        if batch:
            yield batch

        logger.info("Coda.io import complete")
