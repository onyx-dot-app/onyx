from enum import StrEnum
from typing import Literal
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

    name: str
    email: Optional[str] = None
    additionalType: Optional[str] = None
    context: str = Field(alias="@context")
    type: Literal[CodaSchemaOrgIdentifier.PERSON] = Field(alias="@type")
