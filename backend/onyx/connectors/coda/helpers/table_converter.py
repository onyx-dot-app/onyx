"""
Convert Coda table rows to pandas DataFrames with proper handling of rich values.
"""

from typing import Any
from typing import Optional

import pandas as pd
from pydantic import BaseModel

from onyx.connectors.coda.models.table.cell import CodaCellValue
from onyx.connectors.coda.models.table.row import CodaRow


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
                table_id = cell_value.get("table_id", "MISSING_TABLE_ID")
                row_id = cell_value.get("row_id", "MISSING_ROW_ID")
                return f"Type: StructuredValue. Name: {name}. URL: {url}. Table ID: {table_id}. Row ID: {row_id}"

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
    def rows_to_dataframe(
        rows: list[CodaRow],
        use_display_values: bool = True,
        include_metadata: bool = True,
    ) -> pd.DataFrame:
        """
        Convert a list of CodaRow objects to a pandas DataFrame.

        Args:
            rows: List of CodaRow objects from the API
            use_display_values: If True, convert rich values to display strings.
                               If False, keep structured data (may not be DataFrame-friendly)
            include_metadata: If True, include row metadata columns (id, index, createdAt, etc.)

        Returns:
            pandas DataFrame with rows as records and columns from the table

        Example:
            >>> rows = [CodaRow(...), CodaRow(...)]
            >>> df = CodaTableConverter.rows_to_dataframe(rows)
            >>> print(df.head())
        """
        if not rows:
            return pd.DataFrame()

        # Extract data from each row
        data = []
        for row in rows:
            row_data = {}

            # Add metadata columns if requested
            if include_metadata:
                row_data["_row_id"] = row.id or "MISSING_ROW_ID"
                row_data["_row_index"] = row.index or "MISSING_ROW_INDEX"
                row_data["_created_at"] = row.createdAt or "MISSING_CREATED_AT"
                row_data["_updated_at"] = row.updatedAt or "MISSING_UPDATED_AT"
                row_data["_browser_link"] = row.browserLink or "MISSING_BROWSER_LINK"

            # Extract column values
            for col_name, cell_value in row.values.items():
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
        rows: list[CodaRow], formats: Optional[list[str]] = None
    ) -> pd.DataFrame:
        """
        Convert rows to multiple formats for evaluation/testing.

        Args:
            rows: List of CodaRow objects
            formats: List of format names to generate. If None, generates all formats.
                    Options: "JSON", "DICT", "CSV", "TSV", "HTML", "LaTeX",
                            "Markdown", "STRING", "NumPy", "XML"

        Returns:
            DataFrame with columns ["Data Format", "Data raw"] containing
            the table data in each format

        Example:
            >>> rows = get_table_rows("table-123")
            >>> eval_df = CodaTableConverter.rows_to_formats(rows)
            >>> print(eval_df)
        """
        # Convert rows to base DataFrame
        df = CodaTableConverter.rows_to_dataframe(rows, use_display_values=True)

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
