"""
Convert Coda table rows to pandas DataFrames with proper handling of rich values.
Enhanced with human-readable column names for LLM consumption.
"""

from typing import Any
from typing import Optional

import pandas as pd
from pydantic import BaseModel

from onyx.connectors.coda.models.table.cell import CodaCellValue
from onyx.connectors.coda.models.table.column import CodaColumn
from onyx.connectors.coda.models.table.row import CodaRow
from onyx.connectors.coda.models.table.table import CodaTable
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodaTableConverter:
    """Convert Coda table rows to pandas DataFrames."""

    @staticmethod
    def extract_cell_value(cell_value: CodaCellValue) -> Any:
        """
        Extract a simple value from a CodaCellValue for DataFrame storage.

        Handles rich values like currency, images, persons, URLs, and row references
        by converting them to human-readable strings or appropriate primitives.

        Args:
            cell_value: The cell value from a Coda row

        Returns:
            Simple value suitable for DataFrame (str, int, float, bool, or list)
        """
        if cell_value is None:
            return None

        if isinstance(cell_value, list):
            return [CodaTableConverter.extract_cell_value(item) for item in cell_value]

        if isinstance(cell_value, (str, int, float, bool)):
            return cell_value

        if isinstance(cell_value, BaseModel):
            cell_value = cell_value.model_dump(by_alias=True)

        if isinstance(cell_value, dict):
            value_type = cell_value.get("@type") or cell_value.get("type")

            if value_type == "MonetaryAmount":
                currency = cell_value.get("currency", "MISSING_CURRENCY")
                amount = cell_value.get("amount", "MISSING_AMOUNT")
                return f"Type: MonetaryAmount. Currency: {currency}. Amount: {amount}"

            elif value_type == "ImageObject":
                url = cell_value.get("url", "MISSING_URL")
                name = cell_value.get("name", "MISSING_NAME")
                status = cell_value.get("status", "MISSING_STATUS")

                return f"Type: ImageObject. URL: {url}. Name: {name}. Status: {status}"

            elif value_type == "Person":
                name = cell_value.get("name", "MISSING_NAME")
                email = cell_value.get("email", "MISSING_EMAIL")
                return f"Type: Person. Name: {name}. Email: {email}"

            elif value_type == "WebPage":
                url = cell_value.get("url", "MISSING_URL")
                name = cell_value.get("name", "MISSING_NAME")
                return f"Type: WebPage. URL: {url}. Name: {name}"

            elif value_type == "StructuredValue":
                name = cell_value.get("name", "MISSING_NAME")
                url = cell_value.get("url", "MISSING_URL")
                table_id = cell_value.get("tableId", "MISSING_TABLE_ID")
                row_id = cell_value.get("rowId", "MISSING_ROW_ID")

                return f"Type: StructuredValue. Name: {name}. URL: {url}. Table ID: {table_id}. {row_id}"

        return str(cell_value)

    @staticmethod
    def extract_display_value(cell_value: CodaCellValue) -> str:
        """
        Extract a display-friendly string from any cell value.

        Args:
            cell_value: The cell value from a Coda row

        Returns:
            Human-readable string representation
        """
        value = CodaTableConverter.extract_cell_value(cell_value)

        if isinstance(value, list):
            return ", ".join(str(v) for v in value)

        return str(value) if value is not None else ""

    @staticmethod
    def _build_column_map(columns: Optional[list[CodaColumn]]) -> dict[str, CodaColumn]:
        """
        Build a mapping from column IDs to human-readable column names.

        Args:
            columns: List of CodaColumn objects with metadata

        Returns:
            Dictionary mapping column ID to column name
        """
        if not columns:
            return {}

        return {col.id: col for col in columns}

    @staticmethod
    def rows_to_dataframe(
        rows: list[CodaRow],
        columns: Optional[list[CodaColumn]] = None,
        use_display_values: bool = True,
        include_metadata: bool = True,
    ) -> pd.DataFrame:
        """
        Convert a list of CodaRow objects to a pandas DataFrame.

        Args:
            rows: List of CodaRow objects from the API
            columns: Optional list of CodaColumn objects for column metadata.
                    If provided, uses human-readable column names instead of IDs.
            use_display_values: If True, convert rich values to display strings.
                               If False, keep structured data (may not be DataFrame-friendly)
            include_metadata: If True, include row metadata columns (id, index, createdAt, etc.)

        Returns:
            pandas DataFrame with rows as records and columns from the table

        Example:
            >>> rows = [CodaRow(...), CodaRow(...)]
            >>> columns = [CodaColumn(...), CodaColumn(...)]
            >>> df = CodaTableConverter.rows_to_dataframe(rows, columns=columns)
            >>> print(df.head())
        """
        if not rows:
            return pd.DataFrame()

        # Build column ID to name mapping
        column_map = CodaTableConverter._build_column_map(columns)

        # Extract data from each row
        data = []
        for row in rows:
            row_data = {}

            # Add metadata columns if requested
            if include_metadata:
                row_data["_row_id"] = row.id or "MISSING_ROW_ID"

                if row.index is not None:
                    row_data["_row_index"] = row.index
                else:
                    row_data["_row_index"] = "MISSING_ROW_INDEX"

                row_data["_created_at"] = row.createdAt or "MISSING_CREATED_AT"
                row_data["_updated_at"] = row.updatedAt or "MISSING_UPDATED_AT"
                row_data["_browser_link"] = row.browserLink or "MISSING_BROWSER_LINK"

            # Extract column values with human-readable names
            for col_id, cell_value in row.values.items():
                # Use human-readable name if available, otherwise fall back to ID
                col = column_map.get(col_id, col_id)
                if isinstance(col, str):
                    col_name = col
                else:
                    col_name = col.name

                logger.debug(f"Column name: {col_name}")

                if use_display_values:
                    row_data[col_name] = CodaTableConverter.extract_display_value(
                        cell_value
                    )
                else:
                    row_data[col_name] = CodaTableConverter.extract_cell_value(
                        cell_value
                    )

            data.append(row_data)

        return pd.DataFrame(data)

    @staticmethod
    def rows_to_formats(
        rows: list[CodaRow],
        columns: Optional[list[CodaColumn]] = None,
        formats: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        Convert rows to multiple formats for evaluation/testing.

        Args:
            rows: List of CodaRow objects
            columns: Optional list of CodaColumn objects for column metadata
            formats: List of format names to generate. If None, generates all formats.
                    Options: "JSON", "DICT", "CSV", "TSV", "HTML", "LaTeX",
                            "Markdown", "STRING", "NumPy", "XML"

        Returns:
            DataFrame with columns ["Data Format", "Data raw"] containing
            the table data in each format

        Example:
            >>> rows = get_table_rows("table-123")
            >>> columns = get_table_columns("table-123")
            >>> eval_df = CodaTableConverter.rows_to_formats(rows, columns=columns)
            >>> print(eval_df)
        """
        # Convert rows to base DataFrame with human-readable column names
        df = CodaTableConverter.rows_to_dataframe(rows, columns)

        # All available formats
        all_formats = [
            "JSON",
            "DICT",
            "CSV",
            "TSV",
            "HTML",
            "LaTeX",
            "Markdown",
            "STRING",
            "NumPy",
            "XML",
        ]

        # Use all formats if none specified
        if formats is None:
            formats = all_formats

        # Create evaluation DataFrame
        eval_df = pd.DataFrame(columns=["Data Format", "Data raw"])

        format_converters = {
            "JSON": lambda df: df.to_json(orient="records"),
            "DICT": lambda df: df.to_dict(orient="records"),
            "CSV": lambda df: df.to_csv(index=False),
            "TSV": lambda df: df.to_csv(index=False, sep="\t"),
            "HTML": lambda df: df.to_html(index=False),
            "LaTeX": lambda df: df.to_latex(index=False),
            "Markdown": lambda df: df.to_markdown(index=False),
            "STRING": lambda df: df.to_string(index=False),
            "NumPy": lambda df: df.to_numpy(),
            "XML": lambda df: df.to_xml(index=False),
        }

        # Generate each requested format
        for format_name in formats:
            if format_name in format_converters:
                try:
                    converted_data = format_converters[format_name](df)
                    eval_df.loc[len(eval_df)] = [format_name, converted_data]
                except Exception as e:
                    eval_df.loc[len(eval_df)] = [format_name, f"Error: {e}"]

        return eval_df

    @staticmethod
    def rows_to_text_sections(
        rows: list[CodaRow],
        columns: Optional[list[CodaColumn]] = None,
        table: Optional[CodaTable] = None,
    ) -> list[TextSection]:
        """
        Convert Coda table rows to an Onyx TextSection.

        Creates a document structure optimized for RAG:
        - Section 1: Table metadata (schema, description, stats)
        - Section 2+: One section per row with all column data

        Args:
            rows: List of CodaRow objects
            columns: Optional list of CodaColumn objects for metadata
            table: Optional CodaTable object for additional metadata

        Returns:
            List of Onyx TextSection objects ready for indexing
        """
        sections: list[TextSection] = []
        column_map = CodaTableConverter._build_column_map(columns)

        # Section 1: Table Metadata
        metadata_lines = ["TABLE METADATA", "=" * 60]

        if table:
            metadata_lines.append(f"Table: {table.name}")
            metadata_lines.append(f"Type: {table.tableType}")
            metadata_lines.append(f"Layout: {table.layout}")
            metadata_lines.append(f"Total Rows: {table.rowCount}")
            metadata_lines.append(f"Link: {table.browserLink}")
            metadata_lines.append("")

            if table.parent:
                metadata_lines.append("PARENT PAGE METADATA")
                metadata_lines.append("=" * 60)
                metadata_lines.append(f"ID: {table.parent.id}")
                metadata_lines.append(f"Name: {table.parent.name}")
                metadata_lines.append(f"Link: {table.parent.browserLink}")

        metadata_lines.append("")

        if columns:
            metadata_lines.append("COLUMN METADATA")
            metadata_lines.append("=" * 60)
            col_info = []

            for col in columns:
                logger.info(col.format)
                # Include column type information for context
                col_type = col.format.get("type", "unknown")
                col_info.append(f"Column: {col.id} Name: {col.name} Type: {col_type}")
            columns_text = "\n".join(col_info)

            metadata_lines.append(columns_text)

        metadata_lines.append("")

        sections.append(
            TextSection(
                link=table.browserLink if table else None,
                text="\n".join(metadata_lines),
            )
        )

        # Sections 2+: One section per row
        for idx, row in enumerate(rows, 1):
            row_lines = []

            row_lines.append(f"--- Row index: {idx} ---")
            row_lines.append("")

            # Add all column values with context
            for col_id, cell_value in row.values.items():
                col_obj = column_map.get(col_id)
                display_value = CodaTableConverter.extract_display_value(cell_value)

                if display_value:
                    row_lines.append(f"{col_obj.name}: {display_value}")

            row_lines.append("")
            row_lines.append("ROW METADATA")
            row_lines.append("=" * 60)
            row_lines.append(f"Row Link: {row.browserLink}")
            row_lines.append(f"Row ID: {row.id}")

            if row.createdAt and row.updatedAt:
                row_lines.append(f"Created: {row.createdAt}")
                row_lines.append(f"Updated: {row.updatedAt}")

            sections.append(
                TextSection(
                    link=row.browserLink,
                    text="\n".join(row_lines),
                )
            )

        return sections
