from collections.abc import Generator

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.helpers.parser import CodaParser
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table import CodaTableReference
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodaDocumentGenerator:
    """Handles generation of Document objects from Coda data.

    Responsibilities:
    - Converting Coda pages and tables into Document objects
    - Building document metadata
    - Filtering content (hidden pages, empty content, etc.)
    - Tracking indexed items to avoid duplicates

    API calls and data transformation are delegated to CodaAPIClient
    and CodaParser respectively.
    """

    def __init__(
        self,
        client: CodaAPIClient,
        parser: CodaParser,
        max_table_rows: int = 1000,
        export_format: str = "markdown",
    ) -> None:
        """Initialize with dependencies.

        Args:
            client: CodaAPIClient for API calls
            parser: CodaParser for data transformation
            max_table_rows: Maximum rows to fetch per table
            export_format: Format for page exports - 'markdown' or 'html'
        """
        self.client = client
        self.parser = parser
        self.max_table_rows = max_table_rows
        self.export_format = export_format
        self.indexed_pages: set[str] = set()
        self.indexed_tables: set[str] = set()

    def generate_page_documents(
        self, doc: CodaDoc, pages: list[CodaPage], page_map: dict[str, CodaPage]
    ) -> Generator[Document, None, None]:
        """Generate Document objects from pages.

        Args:
            doc: The parent document
            pages: List of pages to process
            page_map: Mapping of page IDs for hierarchy lookup

        Yields:
            Document: Page documents with metadata and content
        """
        for page in pages:
            # Skip hidden pages
            if page.isHidden:
                logger.debug(f"Skipping hidden page '{page.name}'.")
                continue

            page_key = f"{doc.id}:{page.id}"

            # Skip already indexed pages
            if page_key in self.indexed_pages:
                logger.debug(f"Already indexed page '{page.name}'. Skipping.")
                continue

            logger.info(f"Reading page '{page.name}' in doc '{doc.name}'")

            # Get page content from API
            content = self.client.export_page_content(
                doc.id, page.id, self.export_format
            )
            if content is None:
                logger.warning(f"Skipping page {page.id}: export failed")
                continue

            if not content.strip():
                logger.debug(f"Skipping page '{page.name}': no content")
                continue

            # Mark as indexed
            self.indexed_pages.add(page_key)

            # Parse page title and content
            page_title = self.parser.build_page_title(page)
            text = self.parser.build_page_content(page_title, content)

            # Build metadata
            metadata: dict[str, str | list[str]] = {
                "doc_name": doc.name,
                "doc_id": doc.id,
                "page_id": page.id,
                "path": self.parser.get_page_path(page, page_map),
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
                    self.parser.parse_timestamp(page.updatedAt.replace("Z", "+00:00"))
                    if page.updatedAt
                    else None
                ),
                metadata=metadata,
            )

    def generate_table_documents(
        self, doc: CodaDoc, tables: list[CodaTableReference]
    ) -> Generator[Document, None, None]:
        """Generate Document objects from tables.

        Args:
            doc: The parent document
            tables: List of tables to process

        Yields:
            Document: Table documents with metadata and markdown content
        """
        for table in tables:
            table_key = f"{doc.id}:table:{table.id}"

            # Skip already indexed tables
            if table_key in self.indexed_tables:
                logger.debug(f"Already indexed table '{table.name}'. Skipping.")
                continue

            logger.info(f"Reading table '{table.name}' in doc '{doc.name}'")

            try:
                # Fetch columns and rows
                columns = self.client.fetch_table_columns(doc.id, table.id)

                if not columns:
                    logger.debug(f"Skipping table '{table.name}': no columns")
                    continue

                rows = self.client.fetch_all_table_rows(
                    doc.id, table.id, max_rows=self.max_table_rows
                )

                if not rows:
                    logger.debug(f"Skipping table '{table.name}': no rows")
                    continue

                # Parse table to markdown
                content = self.parser.convert_table_to_markdown(table, columns, rows)

                # Mark as indexed
                self.indexed_tables.add(table_key)

                # Build metadata
                metadata: dict[str, str | list[str]] = {
                    "doc_name": doc.name,
                    "doc_id": doc.id,
                    "table_id": table.id,
                    "table_name": table.name,
                    "row_count": str(len(rows)),
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
                    doc_updated_at=self.parser.parse_timestamp(
                        doc.updatedAt.replace("Z", "+00:00")
                    ),
                    metadata=metadata,
                )

            except Exception as e:
                logger.warning(
                    f"Error processing table '{table.name}' in doc '{doc.name}': {e}"
                )
                continue

    def generate_all_documents(
        self, doc_ids: set[str] | None = None, include_tables: bool = True
    ) -> Generator[Document, None, None]:
        """Generate all documents from accessible Coda workspace.

        Args:
            doc_ids: Optional set of doc IDs to process. If None, processes all.
            include_tables: Whether to include table documents

        Yields:
            Document: All page and table documents
        """
        logger.info("Starting full load of Coda docs and pages")

        for doc in self.client.fetch_all_docs():
            # Filter by doc_ids if specified
            if doc_ids and doc.id not in doc_ids:
                continue

            logger.info(f"Processing doc: {doc.name}")

            # Fetch all pages for this doc to build hierarchy
            all_pages = self.client.fetch_all_pages(doc.id)

            # Build map for hierarchy
            page_map = {p.id: p for p in all_pages}

            # Generate documents from pages
            yield from self.generate_page_documents(doc, all_pages, page_map)

            # Process tables if enabled
            if include_tables:
                all_tables = self.client.fetch_all_tables(doc.id)

                if all_tables:
                    yield from self.generate_table_documents(doc, all_tables)

    def generate_updated_documents(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        doc_ids: set[str] | None = None,
        include_tables: bool = True,
    ) -> Generator[Document, None, None]:
        """Generate documents that were updated within a time period.

        Args:
            start: Start of time window (seconds since epoch)
            end: End of time window (seconds since epoch)
            doc_ids: Optional set of doc IDs to process. If None, processes all.
            include_tables: Whether to include table documents

        Yields:
            Document: Updated page and table documents
        """
        logger.info(f"Polling Coda for updates between {start} and {end}")

        for doc in self.client.fetch_all_docs():
            # Filter by doc_ids if specified
            if doc_ids and doc.id not in doc_ids:
                continue

            doc_updated_at = self.parser.parse_timestamp(doc.updatedAt)

            # Skip docs outside time window
            if doc_updated_at.timestamp() < start or doc_updated_at.timestamp() > end:
                continue

            logger.info(f"Processing updated doc: {doc.name}")

            # Fetch all pages for this doc to build hierarchy
            all_pages = self.client.fetch_all_pages(doc.id)
            page_map = {p.id: p for p in all_pages}

            # Filter pages by update time
            updated_pages = []
            for page in all_pages:
                if not page.updatedAt:
                    continue
                page_updated_at = self.parser.parse_timestamp(page.updatedAt)
                if start < page_updated_at.timestamp() < end:
                    updated_pages.append(page)

            if updated_pages:
                # Generate documents from updated pages
                yield from self.generate_page_documents(doc, updated_pages, page_map)

            # Process tables for updated docs if enabled
            # Since tables don't have individual timestamps, we re-index all tables
            # for any doc that has been updated
            if include_tables:
                all_tables = self.client.fetch_all_tables(doc.id)

                if all_tables:
                    yield from self.generate_table_documents(doc, all_tables)
