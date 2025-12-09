from enum import StrEnum
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic.fields import Field


class CodaLinkedDataType(StrEnum):
    """A schema.org identifier for the object."""

    MONETARY_AMOUNT = "MonetaryAmount"
    IMAGE_OBJECT = "ImageObject"
    PERSON = "Person"
    WEB_PAGE = "WebPage"
    STRUCTURED_VALUE = "StructuredValue"


class CodaScalarValue(BaseModel):
    """Represents a scalar value in a Coda table row"""

    str | int | float | bool


class CodaCurrencyAmount(BaseModel):
    """A numeric monetary amount as a string or number."""

    str | int | float


class LinkedDataObject(BaseModel):
    """Base type for a JSON-LD (Linked Data) object."""

    context: CodaLinkedDataType = (
        Field(
            description="A url describing the schema context for this object, typically",
            alias="@context",
        ),
    )
    type: CodaLinkedDataType = Field(
        description="The type of the value.", alias="@type"
    )
    additionalType: str = Field(
        description="An identifier of additional type info specific to Coda that may not be present in a schema.org taxonomy."
    )


class CodaCurrencyValue(LinkedDataObject):
    """Represents a currency value in a Coda table row"""

    type: CodaLinkedDataType.MONETARY_AMOUNT = Field(
        description="The type of the value.", alias="@type"
    )
    currency: str = Field(description="The 3-letter currency code.")
    amount: CodaCurrencyAmount


class CodaImageStatus(StrEnum):
    """The status of an image."""

    LIVE = "live"
    DELETED = "deleted"
    FAILED = "failed"


class CodaImageUrlValue(LinkedDataObject):
    """Represents an image URL value in a Coda table row"""

    type: CodaLinkedDataType.IMAGE_OBJECT = Field(
        description="The type of the value.", alias="@type"
    )
    name: str = Field(description="The name of the image.")
    url: Optional[str] = Field(description="The URL of the image.")
    height: int = Field(description="The height of the image in pixels.")
    width: int = Field(description="The width of the image in pixels.")
    status: Optional[CodaImageStatus] = Field(description="The status of the image.")


class CodaPersonValue(LinkedDataObject):
    """Represents a person value in a Coda table row"""

    type: CodaLinkedDataType.PERSON = Field(
        description="The type of the value.", alias="@type"
    )
    name: str = Field(description="The full name of the person.")
    email: str = Field(description="The email address of the person.")


class CodaUrlValue(LinkedDataObject):
    """Represents a URL value in a Coda table row"""

    type: CodaLinkedDataType.WEB_PAGE = Field(
        description="The type of the value.", alias="@type"
    )
    url: str = Field(description="The URL.")
    name: Optional[str] = Field(description="The user-visible text of the hyperlink.")


class CodaRowValue(LinkedDataObject):
    """Represents a row value in a Coda table row"""

    type: CodaLinkedDataType.STRUCTURED_VALUE = Field(
        description="The type of the value.", alias="@type"
    )
    name: Optional[str] = Field(description="The name of the row.")
    url: Optional[str] = Field(description="The URL of the row.")
    tableId: Optional[str] = Field(description="The ID of the table.")
    tableUrl: Optional[str] = Field(description="The URL of the table.")
    rowId: Optional[str] = Field(description="The ID of the row.")


CodaRichSingleValue = Union[
    CodaScalarValue,
    CodaCurrencyValue,
    CodaImageUrlValue,
    CodaPersonValue,
    CodaUrlValue,
    CodaRowValue,
]

CodaRichValue = Union[CodaRichSingleValue, list[CodaRichSingleValue]]

Value = Union[CodaScalarValue, list[CodaScalarValue]]

CodaCellValue = Union[CodaRichValue, Value]
