from enum import StrEnum
from typing import Optional

from onyx.connectors.coda.models.common import CodaObjectBase


class CodaSchemaOrgIdentifier(StrEnum):
    """
    Represents the allowed string values for schema.org identifier.
    """

    PERSON = "Person"
    IMAGE_OBJECT = "ImageObject"
    MONETARY_AMOUNT = "MonetaryAmount"
    WEB_PAGE = "WebPage"
    STRUCTURED_VALUE = "StructuredValue"


class CodaPersonValue(CodaObjectBase):
    """Represents a Coda Person object"""

    context: str
    type: CodaSchemaOrgIdentifier
    name: str
    additionalType: Optional[str] = None
    email: Optional[str] = None
