from datetime import datetime
from datetime import timezone
from typing import Any

from bs4 import BeautifulSoup
from bs4 import NavigableString
from bs4 import Tag
from dateutil import parser as date_parser

from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table import CodaColumn
from onyx.connectors.coda.models.table import CodaRow
from onyx.connectors.coda.models.table import CodaTableReference
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodaParser:
    """Handles parsing and transformation of Coda data.

    Responsibilities:
    - Converting raw Coda objects into formatted content (markdown, etc.)
    - Parsing timestamps
    - Building page hierarchies and paths
    - Formatting cell values for display
    """

    @staticmethod
    def parse_timestamp(timestamp_str: str) -> datetime:
        """Robustly parse ISO 8601 timestamps to UTC.

        Args:
            timestamp_str: ISO 8601 formatted timestamp string

        Returns:
            datetime: Parsed timestamp in UTC timezone
        """
        dt = date_parser.isoparse(timestamp_str)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def get_page_path(page: CodaPage, page_map: dict[str, CodaPage]) -> str:
        """Constructs the breadcrumb path for a page.

        Walks up the page hierarchy using the parent chain and builds
        a human-readable path like "Parent / Child / Page".

        Args:
            page: The page to get the path for
            page_map: Mapping of all page IDs to page objects for hierarchy lookup

        Returns:
            str: Breadcrumb path separated by " / "
        """
        path_parts = [page.name]
        current_page = page

        while current_page.parent:
            parent_id = current_page.parent.id
            if not parent_id or parent_id not in page_map:
                break
            current_page = page_map[parent_id]
            path_parts.append(current_page.name)

        return " / ".join(reversed(path_parts))

    @staticmethod
    def format_cell_value(value: Any) -> str:
        """Format a cell value for markdown table display.

        Handles various Coda value types:
        - Dicts with "name" or "url" keys
        - Lists (joined with commas)
        - Booleans (rendered as ✓ or empty)
        - Strings with special character escaping

        Args:
            value: The cell value to format

        Returns:
            str: Formatted value safe for markdown table display
        """
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
            # Join list items with commas
            return ", ".join(str(item) for item in value)
        elif isinstance(value, bool):
            # Render booleans as checkmark or empty
            return "✓" if value else ""
        else:
            # Escape pipe characters and newlines for markdown tables
            return str(value).replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def convert_table_to_markdown(
        table: CodaTableReference,
        columns: list[CodaColumn],
        rows: list[CodaRow],
    ) -> str:
        """Convert table data to markdown format.

        Generates a markdown table with headers, separator row, and data rows.
        Only includes columns marked as displayable.

        Args:
            table: The table metadata (name, etc.)
            columns: List of column definitions
            rows: List of row data (may be truncated)

        Returns:
            str: Markdown formatted table string
        """
        # Handle empty cases
        if not columns:
            return f"# {table.name}\n\n*Empty table - no columns defined*"

        if not rows:
            return f"# {table.name}\n\n*Empty table - no data*"

        # Build column name to ID mapping for displayable columns only
        col_id_to_name = {col.id: col.name for col in columns if col.display}

        if not col_id_to_name:
            return f"# {table.name}\n\n*No displayable columns*"

        # Build markdown table
        lines = [f"# {table.name}\n"]

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
                cells.append(CodaParser.format_cell_value(value))
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    @staticmethod
    def build_page_title(page: CodaPage) -> str:
        """Build the display title for a page.

        Combines page name and subtitle if present.
        Falls back to a generic title if page name is missing.

        Args:
            page: The page to build a title for

        Returns:
            str: The formatted page title
        """
        page_title = page.name or f"Untitled Page {page.id}"

        if page.subtitle:
            page_title = f"{page_title} - {page.subtitle}"

        return page_title

    @staticmethod
    def build_page_content(title: str, markdown_content: str) -> str:
        """Build the full text content for a page document.

        Combines the page title with the exported markdown content.

        Args:
            title: The page title
            markdown_content: The markdown content exported from Coda

        Returns:
            str: The combined content ready for document indexing
        """
        return f"{title}\n\n{markdown_content}"

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
                if text:
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

        flush_text()
        return sections

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
            "path": CodaParser.get_page_path(page, page_map),
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
    def build_table_metadata(
        doc: CodaDoc,
        table: CodaTableReference,
        columns: list[CodaColumn],
        rows: list[CodaRow],
    ) -> dict[str, str | list[str]]:
        """Build metadata dictionary for a table document.

        Creates a metadata dict with table information including row/column counts.

        Args:
            doc: The parent document
            table: The table to build metadata for
            columns: List of column definitions
            rows: List of row data

        Returns:
            dict: Metadata dictionary with table information
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
        }

        return metadata
