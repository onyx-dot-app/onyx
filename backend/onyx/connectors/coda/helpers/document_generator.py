from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Optional

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.helpers.parser import CodaParser
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table.table import CodaTableReference
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
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
        page_ids: Optional[set[str]] = None,
        doc_ids: Optional[set[str]] = None,
        include_tables: bool = True,
    ) -> None:
        """Initialize with dependencies.

        Args:
            client: CodaAPIClient for API calls
            parser: CodaParser for data transformation
            page_ids: Optional set of page IDs to index. If None, indexes all.
            doc_ids: Optional set of doc IDs to index. If None, indexes all.
            include_tables: Whether to include table documents
        """
        self.client = client
        self.parser = parser
        self.page_ids: Optional[set[str]] = page_ids
        self.doc_ids: Optional[set[str]] = doc_ids
        self.include_tables: bool = include_tables
        self.indexed_pages: set[str] = set()
        self.indexed_tables: set[str] = set()
        self.skipped_pages: set[str] = set()
        self.skipped_docs: set[str] = set()

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
                self.skipped_pages.add(page.id)
                continue

            page_key = self.create_page_key(doc.id, page.id)

            # Skip already indexed pages
            if page_key in self.indexed_pages:
                logger.debug(f"Already indexed page '{page.name}'. Skipping.")
                continue

            logger.info(f"Reading page '{page.name}' in doc '{doc.name}'")

            # Get page content from API
            content = self.client.export_page_content(doc.id, page.id, "html")

            if content is None:
                self.skipped_pages.add(page.id)
                logger.warning(f"Skipping page {page.id}: export failed")
                continue

            if not content.strip():
                self.skipped_pages.add(page.id)
                logger.debug(f"Skipping page '{page.name}': no content")
                continue

            # Mark as indexed
            self.indexed_pages.add(page_key)

            # Parse page title and content
            page_title = self.parser.build_page_title(page)
            sections = self.parser.parse_html_content(content)

            # Build metadata
            metadata = self.parser.build_page_metadata(doc, page, page_map)

            # Build owners
            primary_owners, secondary_owners = self.parser.build_page_owners(page)

            if len(sections) == 0:
                self.skipped_pages.add(page.id)
                logger.debug(f"Skipping page '{page_title}': no content")
                continue

            yield Document(
                id=page_key,
                sections=sections,
                source=DocumentSource.CODA,
                semantic_identifier=page_title,
                doc_updated_at=(
                    datetime.fromtimestamp(
                        self.parser.parse_timestamp(
                            page.updatedAt.replace("Z", "+00:00")
                        ),
                        tz=timezone.utc,
                    )
                    if page.updatedAt
                    else None
                ),
                metadata=metadata,
                primary_owners=primary_owners,
                secondary_owners=secondary_owners,
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
            table_key = self.parser.create_table_key(doc, table)

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

                content = self.parser.convert_table_to_text(table, columns, rows)
                self.indexed_tables.add(table_key)

                metadata = self.parser.build_table_metadata(
                    doc, table, columns, rows, parent_page_id=table.parent.id
                )
                primary_owners = self.parser.build_doc_owners(doc)

                sections = [TextSection(text=content, link=None)]

                yield Document(
                    id=table_key,
                    sections=sections,
                    source=DocumentSource.CODA,
                    semantic_identifier=f"{doc.name} - {table.name}",
                    doc_updated_at=datetime.fromtimestamp(
                        self.parser.parse_timestamp(
                            doc.updatedAt.replace("Z", "+00:00")
                        ),
                        tz=timezone.utc,
                    ),
                    metadata=metadata,
                    primary_owners=primary_owners,
                )

            except Exception as e:
                logger.warning(
                    f"Error processing table '{table.name}' in doc '{doc.name}': {type(e).__name__}: {e}"
                )
                continue

    def filter_by_id(
        self,
        object_ids: set[str] | None,
        objects: list[CodaDoc] | list[CodaTableReference],
    ) -> list[CodaDoc] | list[CodaTableReference]:
        filtered = []
        if object_ids:
            for object in objects:
                if object.id in object_ids:
                    filtered.append(object)
                else:
                    if isinstance(object, CodaDoc):
                        self.skipped_docs.add(object.id)
                        logger.debug(
                            f"Skipping doc: {object.name}:{object.id}, not found in doc_ids to process"
                        )
                    else:
                        self.skipped_pages.add(object.id)
                        logger.debug(
                            f"Skipping page: {object.name}:{object.id}, not found in page_ids to process"
                        )
            return filtered
        else:
            logger.debug("No filter to apply.")
            return objects

    def filter_by_update_time(
        self,
        objects: list[CodaDoc] | list[CodaPage],
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> list[CodaDoc] | list[CodaPage]:
        """Filter docs and pages based on update time."""

        updated_objects = []
        for object in objects:
            if not object.updatedAt:
                if isinstance(object, CodaDoc):
                    logger.debug(f"Skipping doc: {object.name} has no update time")
                    self.skipped_docs.add(object.id)
                else:
                    logger.debug(f"Skipping page: {object.name} has no update time")
                    self.skipped_pages.add(object.id)
                continue

            object_updated_at = self.parser.parse_timestamp(object.updatedAt)

            if start - 20000 < object_updated_at < end + 20000:
                logger.debug(
                    f"Processing doc: {object.name} updated within time range at: {object_updated_at}."
                    f"Start: {start - 20000}, End: {end + 20000}"
                )
                updated_objects.append(object)
            else:
                if isinstance(object, CodaDoc):
                    self.skipped_docs.add(object.id)
                    logger.debug(
                        f"Skipping doc: {object.name} updated outside time range at: {object_updated_at}."
                        f"Start: {start - 20000}, End: {end + 20000}"
                    )
                else:
                    self.skipped_pages.add(object.id)
                    logger.debug(
                        f"Skipping page: {object.name} updated outside time range at: {object_updated_at}."
                        f"Start: {start - 20000}, End: {end + 20000}"
                    )

        return updated_objects

    def generate_all_documents(
        self,
    ) -> Generator[Document, None, None]:
        """Generate all documents from accessible Coda workspace.

        Args:
            doc_ids: Optional set of doc IDs to process. If None, processes all.
            page_ids: Optional set of page IDs to process. If None, processes all.
            include_tables: Optional boolean to include table documents. Defaults to True.

        Yields:
            Document: All page and table documents
        """
        logger.info("Starting full load of Coda docs and pages")

        all_docs = self.client.fetch_all_docs()

        filtered_docs: list[CodaDoc] = self.filter_by_id(self.doc_ids, all_docs)

        for doc in filtered_docs:
            logger.info(f"Processing doc: {doc.name}")

            # Fetch all pages for this doc to build hierarchy
            all_pages = self.client.fetch_all_pages(doc.id)

            # Filter pages if page_ids specified
            pages_to_process = self.filter_by_id(self.page_ids, all_pages)

            # Build map for hierarchy
            page_map = self.parser.create_page_map(pages_to_process)

            # Generate documents from pages
            yield from self.generate_page_documents(doc, pages_to_process, page_map)

            # Process tables if enabled
            if self.include_tables:
                all_tables = self.client.fetch_all_tables(doc.id)

                if all_tables:
                    yield from self.generate_table_documents(doc, all_tables)

    def generate_updated_documents(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
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

        all_docs = self.client.fetch_all_docs()

        updated_docs = self.filter_by_update_time(all_docs, start, end)

        filtered_docs = self.filter_by_id(self.doc_ids, updated_docs)

        for doc in filtered_docs:
            logger.info(f"Processing doc: {doc.name}")

            # Fetch all pages for this doc to build hierarchy
            all_pages = self.client.fetch_all_pages(doc.id)

            # Filter pages if page_ids specified
            filtered_pages = self.filter_by_id(self.page_ids, all_pages)

            # Filter pages by update time
            pages_to_process = self.filter_by_update_time(filtered_pages, start, end)

            # Build map for hierarchy
            page_map = self.parser.create_page_map(pages_to_process)

            # Generate documents from pages
            yield from self.generate_page_documents(doc, pages_to_process, page_map)

            # Process tables if enabled
            if self.include_tables:
                all_tables = self.client.fetch_all_tables(doc.id)

                if all_tables:
                    yield from self.generate_table_documents(doc, all_tables)

    def generate_all_slim_documents(self) -> Generator[SlimDocument, None, None]:
        """Generate slim documents (IDs only) for all accessible Coda content.

        Args:
            doc_ids: Optional set of doc IDs to process. If None, processes all.
            include_tables: Whether to include table documents

        Yields:
            SlimDocument: Slim documents for all pages and tables
        """
        logger.info("Fetching all Coda doc IDs for deletion detection")

        all_docs = self.client.fetch_all_docs()
        filtered_docs = self.filter_by_id(self.doc_ids, all_docs)

        for doc in filtered_docs:
            # Fetch all pages
            all_pages = self.client.fetch_all_pages(doc.id)
            filtered_pages = self.filter_by_id(self.page_ids, all_pages)

            for page in filtered_pages:
                page_key = self.parser.create_page_key(doc, page)
                yield SlimDocument(id=page_key)

            # Fetch all tables if enabled
            if self.include_tables:
                all_tables = self.client.fetch_all_tables(doc.id)
                for table in all_tables:
                    table_key = self.parser.create_table_key(doc, table)
                    yield SlimDocument(id=table_key)
