from datetime import timezone
from typing import Optional

from bs4 import BeautifulSoup
from bs4 import NavigableString
from bs4 import Tag
from dateutil import parser as date_parser

from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table.cell import CodaCellValue
from onyx.connectors.coda.models.table.column import CodaColumn
from onyx.connectors.coda.models.table.row import CodaRow
from onyx.connectors.coda.models.table.table import CodaTableReference
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection


class CodaParser:
    """Handles parsing and transformation of Coda data.

    Responsibilities:
    - Converting raw Coda objects into formatted content (markdown, etc.)
    - Parsing timestamps
    - Building page hierarchies and paths
    - Formatting cell values for display
    """

    # ========================================================================
    # Document parsing
    # ========================================================================
    @staticmethod
    def build_doc_owners(doc: CodaDoc) -> list[BasicExpertInfo] | None:
        """Build owner list for a document (used for tables).

        Since tables don't have individual authors, we use the doc owner.

        Args:
            doc: The document to extract owner from

        Returns:
            list: Owner list or None if no owner info
        """
        if doc.ownerName or doc.owner:
            return [BasicExpertInfo(display_name=doc.ownerName, email=doc.owner)]
        return None

    # ========================================================================
    # Page parsing
    # ========================================================================
    @staticmethod
    def create_page_map(pages: list[CodaPage]) -> dict[str, CodaPage]:
        """Create a mapping of page IDs to page objects."""
        return {page.id: page for page in pages}

    @staticmethod
    def parse_timestamp(timestamp_str: str) -> float:
        """
        Robustly parse ISO 8601 timestamps to Unix timestamp format.

        Args:
            timestamp_str: ISO 8601 formatted timestamp string

        Returns:
            float: Parsed timestamp as Unix timestamp in seconds (UTC)

        Raises:
            ValueError: If timestamp_str is not a valid ISO 8601 format
        """
        if not timestamp_str or not isinstance(timestamp_str, str):
            raise ValueError(
                f"Invalid timestamp: expected non-empty string, got {type(timestamp_str).__name__}"
            )

        try:
            dt = date_parser.isoparse(timestamp_str)
            # Ensure timezone-aware datetime (assume UTC if naive)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).timestamp()
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid timestamp format: '{timestamp_str}'. "
                f"Expected ISO 8601 format (e.g., '2025-12-09T19:47:48.000Z'). "
                f"Error: {e}"
            )

    @staticmethod
    def build_semantic_identifier(
        page: CodaPage, separator: str = " / ", max_length: Optional[int] = None
    ) -> str:
        """
        Build the semantic identifier for a page.

        Combines page name and subtitle if present.
        Falls back to a generic title if page name is missing.

        Args:
            page: The page to build a title for
            separator: String to separate name and subtitle (default: " - ")
            max_length: Maximum title length; truncates with "..." if exceeded (default: None)

        Returns:
            str: The formatted page title

        Examples:
            >>> page = CodaPage(id="p1", name="Getting Started")
            >>> build_semantic_identifier(page)
            "Getting Started"

            >>> page = CodaPage(id="p1", name="Guide", subtitle="Introduction")
            >>> build_semantic_identifier(page)
            "Guide - Introduction"

            >>> page = CodaPage(id="p1", name="")
            >>> build_semantic_identifier(page)
            "Untitled Page (p1)"
        """
        if not page:
            raise ValueError("Page cannot be None")

        page_name = (page.name or "").strip()

        if not page_name:
            page_title = f"Untitled Page ({page.id})"
        else:
            page_title = page_name

        # Add subtitle if present
        if page.subtitle:
            subtitle = page.subtitle.strip()
            if subtitle:
                page_title = f"{page_title}{separator}{subtitle}"

        if max_length and len(page_title) > max_length:
            page_title = page_title[: max_length - 3] + "..."

        return page_title

    @staticmethod
    def create_page_key(
        doc_id: str,
        page_id: str,
        separator: str = ":",
    ) -> str:
        """
        Create a unique key for a page. Used as Onyx.Document.id

        Using string IDs instead of objects makes the function more flexible
        and easier to test. Also avoids None reference issues.

        Args:
            doc_id: Document ID
            page_id: Page ID

        Returns:
            str: Unique key in format "doc_id:page:page_id"

        Raises:
            ValueError: If either ID is empty

        Example:
            >>> create_page_key("doc-123", "page-456")
            "doc-123:page-456"
        """
        if not doc_id or not isinstance(doc_id, str):
            raise ValueError(f"doc_id must be a non-empty string, got: {doc_id}")

        if not page_id or not isinstance(page_id, str):
            raise ValueError(f"page_id must be a non-empty string, got: {page_id}")

        return f"{doc_id}{separator}page{separator}{page_id}"

    @staticmethod
    def build_page_owners(
        page: CodaPage,
    ) -> tuple[list[BasicExpertInfo] | None, list[BasicExpertInfo] | None]:
        """Build primary and secondary owner lists for a page.

        Primary owners are the page authors (content creators).
        Secondary owners are the creator and last updater (lifecycle managers).

        Args:
            page: The page to extract owners from

        Returns:
            tuple: (primary_owners, secondary_owners) lists or None if empty
        """
        # Primary owners: page authors
        primary_owners: list[BasicExpertInfo] = []
        if page.authors:
            for author in page.authors:
                if author.name or author.email:
                    primary_owners.append(
                        BasicExpertInfo(display_name=author.name, email=author.email)
                    )

        # Secondary owners: creator and updater
        secondary_owners: list[BasicExpertInfo] = []

        # Add creator
        if page.createdBy and (page.createdBy.name or page.createdBy.email):
            created_by = BasicExpertInfo(
                display_name=page.createdBy.name, email=page.createdBy.email
            )
            secondary_owners.append(created_by)

        # Add updater (if different from creator)
        if page.updatedBy and (page.updatedBy.name or page.updatedBy.email):
            updated_by = BasicExpertInfo(
                display_name=page.updatedBy.name, email=page.updatedBy.email
            )
            # Only add if different from creator
            if not secondary_owners or updated_by != secondary_owners[0]:
                secondary_owners.append(updated_by)

        return (
            primary_owners if primary_owners else None,
            secondary_owners if secondary_owners else None,
        )

    @staticmethod
    def build_page_metadata(
        doc: CodaDoc, page: CodaPage, page_map: dict[str, CodaPage]
    ) -> dict[str, str | list[str]]:
        """Build metadata dictionary for a page document.

        Creates a metadata dict with comprehensive page information including
        hierarchy path, parent relationships, content type, authorship, and
        timestamps for enhanced searchability and context.

        Args:
            doc: The parent document
            page: The page to build metadata for
            page_map: Mapping of page IDs for hierarchy lookup

        Returns:
            dict: Metadata dictionary with page information
        """

        metadata: dict[str, str | list[str]] = {
            "coda_object_type": CodaObjectType.PAGE,
            "doc_name": doc.name,
            "doc_id": doc.id,
            "workspace_id": doc.workspace.id,
            "workspace_name": doc.workspace.name,
            "doc_owner_name": doc.ownerName,
            "doc_owner_email": doc.owner,
            "doc_categories": (
                [cat.name for cat in doc.published.category] if doc.published else None
            ),
            "folder_name": doc.folder.name,
            "workspace_organizationId": doc.workspace.organizationId,
            "doc_mode": doc.published.mode if doc.published else None,
            "doc_published": doc.published.discoverable if doc.published else None,
            "page_id": page.id,
            "folder_id": doc.folder.id,
            "page_name": page.name,
            "content_type": page.contentType,
            "browser_link": page.browserLink,
            "subtitle": page.subtitle,
            "parent_page_id": page.parent.id if page.parent else None,
            "parent_page_name": page.parent.name if page.parent else None,
            "created_by_name": page.createdBy.name if page.createdBy else None,
            "created_by_email": page.createdBy.email if page.createdBy else None,
            "updated_by_name": page.updatedBy.name if page.updatedBy else None,
            "updated_by_email": page.updatedBy.email if page.updatedBy else None,
            "created_at": page.createdAt if page.createdAt else None,
            "updated_at": page.updatedAt if page.updatedAt else None,
            "child_count": str(len(page.children)),
            "child_page_ids": [child.id for child in page.children],
        }

        return {k: v for k, v in metadata.items() if v is not None}

    @staticmethod
    def parse_html_content(content: str) -> list[TextSection | ImageSection]:
        """Parse HTML content into text and image sections.

        Args:
            content: Raw HTML content string

        Returns:
            list[TextSection | ImageSection]: List of parsed sections
        """
        if not content:
            return []

        soup = BeautifulSoup(content, "html.parser")
        sections: list[TextSection | ImageSection] = []
        current_text = []

        def flush_text() -> None:
            if current_text:
                text = "".join(current_text).strip()
                if text and len(text) > 5 and text is not None:
                    sections.append(TextSection(text=text, link=None))
                current_text.clear()

        body = soup.body if soup.body else soup

        for element in body.descendants:
            if isinstance(element, NavigableString):
                text = str(element)
                if text.strip():
                    current_text.append(text)
            elif isinstance(element, Tag):
                if element.name == "img":
                    flush_text()
                    src = element.get("src")
                    if src:
                        sections.append(
                            ImageSection(
                                link=str(src), text=None, image_file_id=str(src)
                            )
                        )
                elif element.name in [
                    "br",
                    "p",
                    "div",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "li",
                ]:
                    # Add newline for block elements to ensure text separation
                    current_text.append("\n")
                elif element.name == "table":
                    # Extract table ID for reference
                    table_id = element.get("data-coda-grid-id")
                    placeholder = f"[[TABLE:{table_id}]]" if table_id else "[[TABLE]]"
                    # Flush any accumulated text before inserting placeholder
                    flush_text()
                    # Create a dedicated TextSection for the placeholder
                    sections.append(TextSection(text=placeholder, link=None))
                    # Remove the table element so its children are not processed
                    element.extract()
                    continue

        flush_text()
        return sections

    # ========================================================================
    # Table parsing
    # ========================================================================
    @staticmethod
    def create_table_key(doc_id: str, table_id: str, separator: str = " / ") -> str:
        """
        Create a unique key for a table.

        Using string IDs instead of objects makes the function more flexible
        and easier to test. Also avoids None reference issues.

        Args:
            doc_id: Document ID
            table_id: Table ID

        Returns:
            str: Unique key in format "doc_id:table:table_id"

        Raises:
            ValueError: If either ID is empty

        Example:
            >>> create_table_key("doc-123", "t-456")
            "doc-123:table:t-456"
        """

        if not doc_id or not isinstance(doc_id, str):
            raise ValueError(f"doc_id must be a non-empty string, got: {doc_id}")

        if not table_id or not isinstance(table_id, str):
            raise ValueError(f"table_id must be a non-empty string, got: {table_id}")

        return f"{doc_id}{separator}table{separator}{table_id}"

    @staticmethod
    def build_table_metadata(
        doc: CodaDoc,
        table: CodaTableReference,
        columns: list[CodaColumn],
        rows: list[CodaRow],
        parent_page_id: str | None = None,
    ) -> dict[str, str | list[str]]:
        """Build metadata dictionary for a table document.

        Creates a metadata dict with table information including row/column counts and optional parent page linkage.
        """
        from onyx.connectors.coda.models.common import CodaObjectType

        metadata: dict[str, str | list[str]] = {
            "type": CodaObjectType.TABLE,
            "doc_name": doc.name,
            "doc_id": doc.id,
            "table_id": table.id,
            "table_name": table.name,
            "row_count": str(len(rows)),
            "column_count": str(len(columns)),
            "parent_page_id": parent_page_id if parent_page_id else None,
        }

        return {k: v for k, v in metadata.items() if v is not None}

    @staticmethod
    def format_cell_value(cell_value: CodaCellValue, column: CodaColumn) -> str:
        """Format a cell value for markdown table display.

        Handles Scalar Values:
        - String
        - Number
        - Boolean

        Args:
            cell_value: The cell value to format
            column_name: The name of the column

        Returns:
            str: Formatted value safe for markdown table display
        """
        formatted_cell_value = f"{column.id}: "

        if isinstance(cell_value, list):
            formatted_cell_value += ", ".join(
                CodaParser.format_cell_value(item) for item in cell_value
            )

        if column.format.type == "boolean":
            formatted_cell_value += str(cell_value) + " [boolean]"

        if column.format.type == "number":
            formatted_cell_value += str(cell_value) + " [number]"

        if column.format.type == "text":
            formatted_cell_value += (
                cell_value.replace("|", "\\|").replace("\n", " ") + " [string]"
            )

        return formatted_cell_value

    @staticmethod
    def convert_table_to_text(
        table: CodaTableReference,
        columns: list[CodaColumn],
        rows: list[CodaRow],
    ) -> str:
        """Convert table data to text format (Key: Value).

        Generates a text representation where each row is a line and cells
        are formatted as "Column Name: Value", separated by tabs.
        This matches the Notion connector's approach for better indexing.

        Args:
            table: The table metadata (name, etc.)
            columns: List of column definitions
            rows: List of row data (may be truncated)

        Returns:
            str: Text formatted table string
        """
        # Handle empty cases
        if not columns:
            return f"{table.name}\n\nEmpty table - no columns defined"

        if not rows:
            return f"{table.name}\n\nEmpty table - no data"

        col_map = {col.id: col for col in columns if col.display}

        text_parts = [f"{table.name}\n"]

        # Data rows
        for row in rows:
            row_parts = []
            for col_id, col_name in col_map.items():
                value = row.values.get(col_id, "")
                formatted_value = CodaParser.format_cell_value(value, col_map[col_id])
                if formatted_value:
                    row_parts.append(f"{col_name}: {formatted_value}")

            if row_parts:
                text_parts.append("\t".join(row_parts))

        return "\n".join(text_parts)
