from enum import StrEnum
from typing import Any
from typing import Literal
from typing import Optional

from pydantic import BaseModel
from typing_extensions import TypedDict

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.page import CodaPageReference


class TableType(StrEnum):
    """
    Represents the allowed string values for table type.
    """

    TABLE = "table"
    VIEW = "view"


class CodaTableReference(CodaObjectBase):
    """Represents a Coda Table reference object"""

    browserLink: str
    type: Literal[CodaObjectType.TABLE]
    tableType: TableType
    parent: Optional[CodaPageReference] = None


class CodaTableFilterFormula(BaseModel):
    """Detailed information about the filter formula for the table, if applicable"""

    valid: bool
    isVolatile: bool
    hasUserFormula: bool
    hasTodayFormula: bool
    hasNowFormula: bool


class CodaColumnReference(BaseModel):
    """Represents a Coda Column reference object"""

    id: str
    type: str
    href: str


class SortDirection(StrEnum):
    """
    Represents the allowed string values for sorting direction.
    """

    ASCENDING = "ascending"
    DESCENDING = "descending"


class CodaTableLayout(StrEnum):
    """
    Represents the valid string values for the layout type of a table or view.
    """

    DEFAULT = "default"
    CARD = "card"
    DETAIL = "detail"
    FORM = "form"
    MASTER_DETAIL = "masterDetail"
    SLIDE = "slide"
    CALENDAR = "calendar"
    GANTT_CHART = "ganttChart"

    AREA_CHART = "areaChart"
    BAR_CHART = "barChart"
    BUBBLE_CHART = "bubbleChart"
    LINE_CHART = "lineChart"
    PIE_CHART = "pieChart"
    SCATTER_CHART = "scatterChart"

    WORD_CLOUD = "wordCloud"


class CodaSortItem(TypedDict):
    """
    Defines the required keys and their types for a single sort instruction.
    """

    column: CodaColumnReference
    direction: SortDirection


class CodaTable(CodaObjectBase):
    """Represents a Coda Table object"""

    browserLink: str
    type: Literal[CodaObjectType.TABLE]
    tableType: TableType
    parent: CodaPageReference
    displayColumn: Optional[CodaColumnReference] = None
    rowCount: int
    sorts: list[CodaSortItem]
    layout: CodaTableLayout
    createdAt: str
    updatedAt: str
    parentTable: Optional[CodaTableReference] = None
    filter: Optional[CodaTableFilterFormula] = None


class CodaRow(CodaObjectBase):
    """Represents a Coda Table Row"""

    type: Literal[CodaObjectType.ROW]
    index: int
    browserLink: str
    createdAt: str
    updatedAt: str
    values: dict[str, Any]
    parent: Optional[CodaTableReference] = None
