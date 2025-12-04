from datetime import datetime
from datetime import timezone
from typing import Any

from dateutil import parser as date_parser

from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table import CodaColumn
from onyx.connectors.coda.models.table import CodaRow
from onyx.connectors.coda.models.table import CodaTableReference
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
