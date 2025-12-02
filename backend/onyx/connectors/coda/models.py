from enum import StrEnum
from typing import Any
from typing import Optional
from typing import TypedDict

from pydantic import BaseModel


class CodaObjectBase(BaseModel):
    id: str
    type: str
    browserLink: str
    name: str


class CodaDoc(CodaObjectBase):
    """Represents a Coda Doc object"""

    owner: str
    ownerName: str
    createdAt: str
    updatedAt: str
    icon: Optional[dict[str, Any]] = None
    docSize: Optional[dict[str, Any]] = None
    sourceDoc: Optional[dict[str, Any]] = None
    published: Optional[dict[str, Any]] = None


class CodaPageReference(CodaObjectBase):
    """Represents a Coda Page reference object"""


class CodaPage(CodaObjectBase):
    """Represents a Coda Page object"""

    subtitle: Optional[str] = None
    icon: Optional[dict[str, Any]] = None
    image: Optional[dict[str, Any]] = None
    contentType: str
    isHidden: bool
    createdAt: str
    updatedAt: str
    parent: Optional[CodaPageReference] = None
    children: list[CodaPageReference]


class CodaTableReference(CodaObjectBase):
    """Represents a Coda Table reference object"""

    parent: CodaPageReference


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


class TableType(StrEnum):
    """
    Represents the allowed string values for table type.
    """

    TABLE = "table"
    VIEW = "view"


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


class SortItem(TypedDict):
    """
    Defines the required keys and their types for a single sort instruction.
    """

    column: CodaColumnReference
    direction: SortDirection


class CodaTable(CodaObjectBase):
    """Represents a Coda Table object"""

    tableType: TableType
    parent: CodaPageReference
    parentTable: Optional[CodaTableReference] = None
    displayColumn: Optional[CodaColumnReference] = None
    rowCount: int
    sorts: list[SortItem]
    layout: CodaTableLayout
    createdAt: str
    updatedAt: str
    filter: Optional[CodaTableFilterFormula] = None


class CodaColumn(BaseModel):
    """Represents a Coda Table Column"""

    id: str
    type: str
    href: str
    name: str
    display: bool
    calculated: bool
    formula: Optional[str] = None
    defaultValue: Optional[str] = None
    format: Optional[dict[str, Any]] = None


class CodaRow(BaseModel):
    """Represents a Coda Table Row"""

    id: str
    type: str
    href: str
    name: str
    index: int
    createdAt: str
    updatedAt: str
    browserLink: str
    values: dict[str, Any]  # Column ID -> value mapping
