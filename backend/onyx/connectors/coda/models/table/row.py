from typing import Literal

from pydantic import Field

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.table.cell import CodaCellValue


class CodaRow(CodaObjectBase):
    """Represents a Coda Table Row"""

    type: Literal[CodaObjectType.ROW]
    index: int = Field(description="Index of the row within the table", example=7)
    browserLink: str = Field(
        description="Browser-friendly link to the row",
        example="https://coda.io/d/_dAbCDeFGH#Teams-and-Tasks_tpqRst-U/_rui-tuVwxYz",
    )
    createdAt: str = Field(
        description="Timestamp of when the row was created",
        example="2024-01-01T00:00:00Z",
    )
    updatedAt: str = Field(
        description="Timestamp of when the row was last updated",
        example="2024-01-01T00:00:00Z",
    )
    values: dict[str, CodaCellValue] = Field(
        description="Values for a specific row, represented as a hash of column IDs (or names with `useColumnNames`) to values.",
        example={"column1": "value1", "column2": "value2"},
    )
