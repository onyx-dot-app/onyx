from enum import StrEnum
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class CodaSchemaOrgIdentifier(StrEnum):
    """
    Represents the allowed string values for schema.org identifier.
    """

    PERSON = "Person"
    IMAGE_OBJECT = "ImageObject"
    MONETARY_AMOUNT = "MonetaryAmount"
    WEB_PAGE = "WebPage"
    STRUCTURED_VALUE = "StructuredValue"


class CodaPersonValue(BaseModel):
    """Represents a Coda Person object"""

    context: str = Field(alias="@context")
    type: CodaSchemaOrgIdentifier = Field(alias="@type")
    name: str
    additionalType: Optional[str] = None
    email: Optional[str] = None
