from enum import StrEnum
from typing import Literal
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic.fields import Field
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


class CodaCellValueType(StrEnum):
    """A schema.org identifier for the object."""

    MONETARY_AMOUNT = "MonetaryAmount"
    IMAGE_OBJECT = "ImageObject"
    PERSON = "Person"
    WEB_PAGE = "WebPage"
    STRUCTURED_VALUE = "StructuredValue"


class ScalarValue(BaseModel):
    """Represents a scalar value in a Coda table row"""

    str | int | float | bool


class CurrencyAmount(BaseModel):
    """A numeric monetary amount as a string or number."""

    str | int | float


class CurrencyValue(BaseModel):
    """Represents a currency value in a Coda table row"""

    context: str = (
        Field(
            description="A url describing the schema context for this object, typically",
            alias="@context",
        ),
    )
    type: CodaCellValueType = Field(description="The type of the value.", alias="@type")
    currency: str = Field(description="The 3-letter currency code.")
    amount: CurrencyAmount
    additionalType: Optional[str] = Field(
        description="An identifier of additional type info specific to Coda that may not be present in a schema.org taxonomy."
    )


class ImageStatus(StrEnum):
    """The status of an image."""

    LIVE = "live"
    DELETED = "deleted"
    FAILED = "failed"


class ImageUrlValue(BaseModel):
    """Represents an image URL value in a Coda table row"""

    context: str = (
        Field(
            description="A url describing the schema context for this object, typically",
            alias="@context",
        ),
    )
    type: CodaCellValueType = Field(description="The type of the value.", alias="@type")
    additionalType: Optional[str] = (
        Field(
            description="An identifier of additional type info specific to Coda that may not be present in a schema.org taxonomy."
        ),
    )
    name: str = Field(description="The name of the image.")
    url: Optional[str] = Field(description="The URL of the image.")
    height: int = Field(description="The height of the image in pixels.")
    width: int = Field(description="The width of the image in pixels.")
    status: Optional[ImageStatus] = Field(description="The status of the image.")


class ParentValue(BaseModel):
    """Represents a parent value in a Coda table row"""

    context: str = Field(
        description="A url describing the schema context for this object, typically.",
        alias="@context",
    )
    type: CodaCellValueType = Field(description="The type of the value.", alias="@type")
    additionalType: Optional[str] = Field(
        description="An identifier of additional type info specific to Coda that may not be present in a schema.org taxonomy."
    )
    email: str = Field(description="The email address of the person.")


class UrlValue(BaseModel):
    """Represents a URL value in a Coda table row"""

    context: str = Field(
        description="A url describing the schema context for this object, typically",
        alias="@context",
    )
    type: CodaCellValueType = Field(description="The type of the value.", alias="@type")
    additionalType: Optional[str] = Field(
        description="An identifier of additional type info specific to Coda that may not be present in a schema.org taxonomy."
    )
    url: str = Field(description="The URL.")
    name: Optional[str] = Field(description="The user-visible text of the hyperlink.")


class RowValue(BaseModel):
    """Represents a row value in a Coda table row"""

    context: str = Field(
        description="A url describing the schema context for this object, typically .",
        alias="@context",
    )
    type: CodaCellValueType = Field(description="The type of the value.", alias="@type")
    name: Optional[str] = Field(description="The name of the row.")
    url: Optional[str] = Field(description="The URL of the row.")
    tableId: Optional[str] = Field(description="The ID of the table.")
    tableUrl: Optional[str] = Field(description="The URL of the table.")
    rowId: Optional[str] = Field(description="The ID of the row.")
    additionalType: Optional[str] = Field(
        description="An identifier of additional type info specific to Coda that may not be present in a schema.org taxonomy."
    )


RichSingleValue = Union[
    ScalarValue,
    CurrencyValue,
    ImageUrlValue,
    ParentValue,
    UrlValue,
    RowValue,
]

RichValue = Union[RichSingleValue, list[RichSingleValue]]

Value = Union[ScalarValue, list[ScalarValue]]

CodaCellValue = Union[RichValue, Value]


class CodaRow(CodaObjectBase):
    """Represents a Coda Table Row"""

    type: Literal[CodaObjectType.ROW]
    index: int
    browserLink: str
    createdAt: str
    updatedAt: str
    values: dict[str, CodaCellValue]
